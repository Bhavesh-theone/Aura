"""Model run lineage rules: how a prompt is hashed, so anyone can re-derive the hash."""
import hashlib
import json
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def prompt_hash(messages: list[dict]) -> str:
    """sha256 of the exact messages sent to the model."""
    return hashlib.sha256(canonical(messages).encode("utf-8")).hexdigest()


def is_traceable(input_digest: dict, stored_hash: str) -> bool:
    """A run is traceable when its stored messages re-hash to the stored prompt hash."""
    messages = (input_digest or {}).get("messages")
    return isinstance(messages, list) and prompt_hash(messages) == stored_hash
