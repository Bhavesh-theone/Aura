"""Connect Aura to a Gmail account (OAuth, Desktop client), and keep the token safe.

    uv run python -m aura.mcp.gmail_auth                      # connect (gmail.compose)
    uv run python -m aura.mcp.gmail_auth --scopes compose,send
    uv run python -m aura.mcp.gmail_auth --status             # who is connected; no tokens
    uv run python -m aura.mcp.gmail_auth --revoke             # forget (and revoke) the token

The token lives in the OS keyring (service 'aura-gmail', key 'token'). Only when no keyring
backend is available does it fall back to an encrypted file (settings.gmail_token_file, its
key beside it), and it says so. Nothing here ever prints or logs a token or the client
secret.

google-auth refreshes the access token. A refresh that fails (a Google app in Testing mode
expires refresh tokens after 7 days: invalid_grant) marks the connection 'needs_reconnect';
the portal then shows "Reconnect Gmail" and outbound email is blocked until this command is
run again.
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from aura.core.domain.outbound import MailerStatus

SERVICE, KEY = "aura-gmail", "token"
SCOPE_URLS = {"compose": "https://www.googleapis.com/auth/gmail.compose",
              "send": "https://www.googleapis.com/auth/gmail.send"}
CONNECT_COMMAND = "uv run python -m aura.mcp.gmail_auth"


class GmailNotConnected(Exception):
    pass


class GmailReconnectNeeded(Exception):
    pass


# --- storage ---------------------------------------------------------------------------------

def _keyring():
    """The OS keyring, or None when only the 'fail' (or a null) backend is available."""
    try:
        import keyring
        from keyring.backends import fail
        backend = keyring.get_keyring()
        if isinstance(backend, fail.Keyring) or getattr(backend, "priority", 1) <= 0:
            return None
        return keyring
    except Exception:
        return None


def _file_paths() -> tuple[Path, Path]:
    from aura.config import get_settings
    token = Path(get_settings().gmail_token_file)
    return token, token.with_name(token.name + ".key")


def _fernet(create: bool):
    from cryptography.fernet import Fernet
    _, key_path = _file_paths()
    if not key_path.exists():
        if not create:
            return None
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(Fernet.generate_key())
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
    return Fernet(key_path.read_bytes())


def load_record() -> tuple[dict | None, str | None]:
    """(stored record, storage name). The record holds the credentials JSON, the account and
    the reconnect flag."""
    kr = _keyring()
    if kr is not None:
        try:
            raw = kr.get_password(SERVICE, KEY)
        except Exception:
            raw = None
        if raw:
            return json.loads(raw), "keyring"
    token_path, _ = _file_paths()
    fernet = _fernet(create=False)
    if token_path.exists() and fernet is not None:
        try:
            return json.loads(fernet.decrypt(token_path.read_bytes())), "encrypted_file"
        except Exception:
            return None, None
    return None, None


def save_record(record: dict) -> str:
    """Store the record; returns where it went ('keyring' or 'encrypted_file')."""
    raw = json.dumps(record, separators=(",", ":"))
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE, KEY, raw)
            return "keyring"
        except Exception:
            pass  # e.g. a credential too large for the backend: fall through to the file
    token_path, _ = _file_paths()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_bytes(_fernet(create=True).encrypt(raw.encode("utf-8")))
    return "encrypted_file"


def delete_record() -> bool:
    removed = False
    kr = _keyring()
    if kr is not None:
        try:
            if kr.get_password(SERVICE, KEY):
                kr.delete_password(SERVICE, KEY)
                removed = True
        except Exception:
            pass
    for path in _file_paths():
        if path.exists():
            path.unlink()
            removed = True
    return removed


# --- status and credentials ------------------------------------------------------------------

def _expiry(record: dict) -> datetime | None:
    value = (record.get("credentials") or {}).get("expiry")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def stored_status() -> MailerStatus:
    """The connection as stored. No network call, never a token."""
    try:
        record, storage = load_record()
    except Exception as exc:
        return MailerStatus(connected=False, detail=f"token store unreadable: "
                                                    f"{type(exc).__name__}")
    if not record:
        return MailerStatus(connected=False, detail="Not connected. Run: " + CONNECT_COMMAND)
    creds = record.get("credentials") or {}
    needs = bool(record.get("needs_reconnect")) or not creds.get("refresh_token")
    return MailerStatus(connected=not needs, account_email=record.get("account"),
                        scopes=tuple(creds.get("scopes") or ()), expires_at=_expiry(record),
                        needs_reconnect=needs, storage=storage,
                        detail="Reconnect Gmail: " + CONNECT_COMMAND if needs else None)


def mark_needs_reconnect(reason: str) -> None:
    record, _ = load_record()
    if record:
        record["needs_reconnect"] = True
        record["reconnect_reason"] = reason[:200]
        save_record(record)


def load_credentials():
    """Valid google Credentials, refreshed if they had expired. Raises GmailNotConnected or
    GmailReconnectNeeded (after marking the connection) when they cannot be used."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    record, _ = load_record()
    if not record:
        raise GmailNotConnected("Gmail is not connected")
    if record.get("needs_reconnect"):
        raise GmailReconnectNeeded("Gmail needs to be reconnected")
    info = record.get("credentials") or {}
    creds = Credentials.from_authorized_user_info(info, info.get("scopes"))
    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            # Testing-mode apps: refresh tokens die after 7 days (invalid_grant).
            mark_needs_reconnect(type(exc).__name__)
            raise GmailReconnectNeeded("Gmail token refresh failed; reconnect Gmail") from None
        record["credentials"] = json.loads(creds.to_json())
        save_record(record)
    return creds, record.get("account")


def _profile_email(creds) -> str:
    from googleapiclient.discovery import build
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    return service.users().getProfile(userId="me").execute().get("emailAddress", "")


# --- CLI -------------------------------------------------------------------------------------

def _scopes(value: str) -> list[str]:
    names = [n.strip() for n in value.split(",") if n.strip()]
    unknown = [n for n in names if n not in SCOPE_URLS]
    if unknown or not names:
        raise SystemExit(f"--scopes takes compose or compose,send (got {value!r})")
    return [SCOPE_URLS[n] for n in names]


def connect(scopes: list[str]) -> int:
    from google_auth_oauthlib.flow import InstalledAppFlow

    from aura.config import get_settings
    secret = Path(get_settings().gmail_client_secret_path)
    if not secret.exists():
        print(f"No OAuth client file at {secret}. Download the Desktop client JSON from Google "
              "Cloud Console and save it there (see RUNNING.md, 'Gmail (outbound email)').")
        return 2
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), scopes)
    print("Opening your browser to sign in to Google...")
    creds = flow.run_local_server(port=0, open_browser=True, prompt="consent",
                                  access_type="offline")
    account = _profile_email(creds)
    storage = save_record({"credentials": json.loads(creds.to_json()), "account": account,
                           "connected_at": datetime.now(timezone.utc).isoformat(),
                           "needs_reconnect": False})
    print(f"Connected as {account}. Scopes: {', '.join(creds.scopes or scopes)}.")
    if storage == "keyring":
        print("Token stored in the OS keyring (service 'aura-gmail').")
    else:
        print("No OS keyring is available: the token is stored ENCRYPTED in "
              f"{_file_paths()[0]} (key beside it). Keep both out of version control.")
    return 0


def status() -> int:
    from aura.config import get_settings
    mode = get_settings().outbound_mode
    stored = stored_status()
    if not stored.connected and not stored.needs_reconnect:
        print(f"Gmail: not connected. Outbound mode: {mode}.")
        print(f"Connect with: {CONNECT_COMMAND}")
        return 0
    if stored.needs_reconnect:
        print(f"Gmail: RECONNECT NEEDED (was {stored.account_email or 'unknown'}). "
              f"Outbound mode: {mode}.")
        print(f"Run: {CONNECT_COMMAND}")
        return 1
    try:
        creds, _ = load_credentials()
        account = _profile_email(creds)
    except GmailReconnectNeeded:
        print(f"Gmail: RECONNECT NEEDED (refresh failed). Run: {CONNECT_COMMAND}")
        return 1
    except Exception as exc:
        print(f"Gmail: stored as {stored.account_email}, but the check failed "
              f"({type(exc).__name__}).")
        return 1
    expiry = creds.expiry.isoformat() + "Z" if creds.expiry else "unknown"
    print(f"Gmail: connected as {account}")
    print(f"Scopes: {', '.join(creds.scopes or stored.scopes)}")
    print(f"Access token expires: {expiry} (refreshed automatically)")
    print(f"Stored in: {stored.storage}. Outbound mode: {mode}.")
    return 0


def revoke() -> int:
    record, _ = load_record()
    token = ((record or {}).get("credentials") or {}).get("refresh_token") \
        or ((record or {}).get("credentials") or {}).get("token")
    if token:
        try:  # best effort: tell Google too
            data = urllib.parse.urlencode({"token": token}).encode()
            urllib.request.urlopen(urllib.request.Request(
                "https://oauth2.googleapis.com/revoke", data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=10)
            print("Revoked at Google.")
        except Exception as exc:
            print(f"Could not revoke at Google ({type(exc).__name__}); removing it locally.")
    print("Gmail token removed." if delete_record() else "No Gmail token was stored.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aura.mcp.gmail_auth",
                                     description="Connect Aura to Gmail (drafts first).")
    parser.add_argument("--scopes", default="compose",
                        help="compose (default) or compose,send")
    parser.add_argument("--status", action="store_true", help="show the connection")
    parser.add_argument("--revoke", action="store_true", help="forget the token")
    args = parser.parse_args(argv)
    if args.status:
        return status()
    if args.revoke:
        return revoke()
    return connect(_scopes(args.scopes))


if __name__ == "__main__":
    sys.exit(main())
