import json
import urllib.error
import urllib.request


def ollama_available(base_url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=timeout):
            return True
    except (urllib.error.URLError, OSError):
        return False


def list_models(base_url: str, timeout: float = 5.0) -> list[str]:
    with urllib.request.urlopen(f"{base_url}/api/tags", timeout=timeout) as response:
        payload = json.load(response)
    return [m.get("name", "") for m in payload.get("models", [])]


def model_digest(base_url: str, model: str, timeout: float = 5.0) -> str:
    """The pulled model's digest (its exact version), or 'unknown' if Ollama cannot say."""
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=timeout) as response:
            payload = json.load(response)
    except (urllib.error.URLError, OSError, ValueError):
        return "unknown"
    for m in payload.get("models", []):
        if m.get("name") == model or m.get("model") == model:
            return str(m.get("digest") or "unknown")
    return "unknown"
