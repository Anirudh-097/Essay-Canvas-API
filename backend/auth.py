"""Single-user authentication helpers for the private Essay Learner app."""

from __future__ import annotations

import base64
import binascii
import getpass
import hashlib
import hmac
import json
import os
import secrets
import time

from dotenv import load_dotenv
from fastapi import HTTPException, Request, status

from .db import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")

SESSION_COOKIE = "essay_learner_session"
DEFAULT_SESSION_DAYS = 7
PBKDF2_ITERATIONS = 310_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def _secret() -> str:
    secret = os.getenv("AUTH_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="AUTH_SECRET is not configured")
    return secret


def _configured_username() -> str:
    username = os.getenv("AUTH_USERNAME")
    if not username:
        raise HTTPException(status_code=500, detail="AUTH_USERNAME is not configured")
    return username


def _configured_password_hash() -> str:
    password_hash = os.getenv("AUTH_PASSWORD_HASH")
    if not password_hash:
        raise HTTPException(status_code=500, detail="AUTH_PASSWORD_HASH is not configured")
    return password_hash


def _session_days() -> int:
    try:
        return max(1, int(os.getenv("AUTH_SESSION_DAYS", DEFAULT_SESSION_DAYS)))
    except ValueError:
        return DEFAULT_SESSION_DAYS


def create_session(username: str) -> str:
    expires_at = int(time.time()) + _session_days() * 24 * 60 * 60
    payload = json.dumps(
        {"username": username, "expires_at": expires_at, "nonce": secrets.token_urlsafe(16)},
        separators=(",", ":"),
    ).encode()
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(_secret().encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _session_username(token: str | None) -> str | None:
    if not token or "." not in token:
        return None
    encoded, supplied_signature = token.rsplit(".", 1)
    expected_signature = hmac.new(_secret().encode(), encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied_signature, expected_signature):
        return None
    try:
        padding = "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded + padding))
        username = payload["username"]
        expires_at = int(payload["expires_at"])
    except (ValueError, KeyError, TypeError, binascii.Error, json.JSONDecodeError):
        return None
    if not isinstance(username, str) or expires_at <= int(time.time()):
        return None
    return username


def authenticate(username: str, password: str) -> bool:
    return hmac.compare_digest(username, _configured_username()) and verify_password(
        password, _configured_password_hash()
    )


def require_auth(request: Request) -> str:
    username = _session_username(request.cookies.get(SESSION_COOKIE))
    if username != _configured_username():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Cookie"},
        )
    return username


def cookie_secure() -> bool:
    return os.getenv("AUTH_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}


def session_max_age() -> int:
    return _session_days() * 24 * 60 * 60


if __name__ == "__main__":
    print(hash_password(getpass.getpass("Password to hash: ")))
