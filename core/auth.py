"""Optional password protection, standard library only.

The app runs on one computer, so this is a simple lock screen rather than a user
system: one password, stored only as a salted scrypt hash in data/local_config.yaml (never in Git).
scrypt is deliberately slow and memory hungry, which makes guessing a stolen hash
expensive, and hmac.compare_digest avoids leaking timing information.
"""

import hashlib
import hmac
import secrets

# Interactive-login parameters recommended for scrypt (about 16 MB of memory per attempt).
_N, _R, _P = 2**14, 8, 1
MIN_LENGTH = 8


def hash_password(password: str) -> dict:
    """Return {"salt", "hash"} as hex strings, ready to store in data/local_config.yaml."""
    if len(password) < MIN_LENGTH:
        raise ValueError(f"Use at least {MIN_LENGTH} characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P)
    return {"salt": salt.hex(), "hash": digest.hex()}


def verify_password(password: str, stored: dict | None) -> bool:
    """True only when the password matches the stored salt and hash."""
    if not stored or not stored.get("salt") or not stored.get("hash"):
        return False
    try:
        salt = bytes.fromhex(stored["salt"])
        expected = bytes.fromhex(stored["hash"])
    except ValueError:
        return False
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P)
    return hmac.compare_digest(digest, expected)
