"""Accounts: password hashing (scrypt), signed bearer tokens (HMAC-SHA256), login throttling.

Standard library only, so there is nothing extra to install.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from collections import defaultdict
from pathlib import Path

TOKEN_TTL = 30 * 24 * 3600
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


# ───────────── password hashing ─────────────
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(got.hex(), h)
    except Exception:
        return False


# ───────────── tokens ─────────────
def _secret() -> bytes:
    env = os.getenv("AUTH_SECRET")
    if env:
        return env.encode()
    # No secret configured: create one next to the database so sessions survive restarts.
    p = Path(os.getenv("DB_PATH", "labs.db")).resolve().with_suffix(".secret")
    if not p.exists():
        p.write_text(secrets.token_hex(32))
        try:
            p.chmod(0o600)
        except OSError:
            pass
    return p.read_text().strip().encode()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(user_id: int) -> str:
    body = _b64(json.dumps({"uid": user_id, "exp": int(time.time()) + TOKEN_TTL}).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(token: str) -> int | None:
    try:
        body, sig = token.split(".")
        want = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, want):
            return None
        data = json.loads(_unb64(body))
        if data["exp"] < time.time():
            return None
        return int(data["uid"])
    except Exception:
        return None


# ───────────── login throttle (in memory; use Redis if you run several workers) ─────────────
_fails: dict[str, list[float]] = defaultdict(list)
WINDOW, MAX_FAILS = 15 * 60, 8


def throttled(key: str) -> bool:
    now = time.time()
    _fails[key] = [t for t in _fails[key] if now - t < WINDOW]
    return len(_fails[key]) >= MAX_FAILS


def record_fail(key: str) -> None:
    _fails[key].append(time.time())


def clear_fails(key: str) -> None:
    _fails.pop(key, None)
