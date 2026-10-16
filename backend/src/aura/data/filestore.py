import hashlib
from pathlib import Path

from aura.config import BACKEND_DIR

DOCS_DIR = BACKEND_DIR / "data" / "docs"


class LocalFileStore:
    """Content-addressed files at backend/data/docs/<sha256>."""

    def __init__(self, root: Path | None = None):
        self.root = root or DOCS_DIR

    def put(self, content: bytes) -> str:
        sha = hashlib.sha256(content).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path(sha)
        if not path.exists():
            path.write_bytes(content)
        return sha

    def path(self, sha256: str) -> Path:
        return self.root / sha256

    def read_bytes(self, sha256: str) -> bytes:
        """The whole stored file (FileNotFoundError when it is missing)."""
        return self.path(sha256).read_bytes()

    def read_head(self, sha256: str, limit: int = 2000) -> str:
        """The first `limit` characters of a stored file, decoded leniently."""
        path = self.path(sha256)
        if not path.exists():
            return ""
        with path.open("rb") as f:
            return f.read(limit * 4).decode("utf-8", errors="replace")[:limit]
