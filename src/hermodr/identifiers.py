"""Canonical bytes, hashes, and opaque identifiers."""

from datetime import datetime
import hashlib
import hmac
import json
import secrets

from .clock import unix_milliseconds


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def source_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def idempotency_key(key: bytes, subject_id: str, device_id: str, value: object) -> str:
    material = canonical_json({"device_id": device_id, "payload": value, "subject_id": subject_id})
    return hmac.new(key, material, hashlib.sha256).hexdigest()


def sortable_id(prefix: str, when: datetime, random_bytes: bytes | None = None) -> str:
    if not prefix.isascii() or not prefix.replace("_", "").isalnum():
        raise ValueError("identifier prefix is invalid")
    entropy = random_bytes if random_bytes is not None else secrets.token_bytes(10)
    if len(entropy) != 10:
        raise ValueError("identifier entropy must be 10 bytes")
    return f"{prefix}_{unix_milliseconds(when):013x}{entropy.hex()}"


def deterministic_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256(canonical_json(parts)).hexdigest()[:32]
    return f"{prefix}_{digest}"
