from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from aura.config import get_settings
from aura.core.domain.user import User

ALGORITHM = "HS256"
_MAX_BCRYPT_BYTES = 72


def _encode(password: str) -> bytes:
    """bcrypt only considers the first 72 bytes; truncate explicitly."""
    return password.encode("utf-8")[:_MAX_BCRYPT_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_encode(plain), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_token(user: User) -> str:
    s = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=s.jwt_ttl_minutes)
    payload = {"sub": str(user.id), "username": user.username,
               "role": user.role.value, "exp": expire}
    return jwt.encode(payload, s.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])
    except JWTError:
        return None
