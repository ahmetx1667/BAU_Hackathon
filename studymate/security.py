"""Password hashing, session-token hashing and the application secret.

Passwords use PBKDF2-HMAC-SHA256 with a per-user random salt. Verification runs
through `hmac.compare_digest` rather than `==`: a plain comparison returns as
soon as two bytes differ, and that timing difference leaks how much of a guess
was correct.

Session tokens are stored hashed for the same reason password hashes are — if
the database leaks, the stored value cannot be replayed as a live cookie.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

from .config import PBKDF2_ITERATIONS, SECRET_PATH


def get_secret() -> bytes:
    """Return the application secret, generating and persisting one if needed.

    Used to sign flash messages (see `sign_flash`). In production this should come
    from the environment; the generated file is a development convenience so the
    app runs on a fresh clone with no setup.
    """
    SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    env_secret = os.environ.get("STUDYMATE_SECRET_KEY")
    if env_secret:
        return env_secret.encode()
    if not SECRET_PATH.exists():
        SECRET_PATH.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        try:
            SECRET_PATH.chmod(0o600)
        except OSError:
            pass  # Windows and some filesystems do not support POSIX modes
    return SECRET_PATH.read_text(encoding="utf-8").strip().encode()


SECRET_KEY = get_secret()


def hash_password(password: str) -> str:
    """Hash a password into `algorithm$iterations$salt$digest`.

    The iteration count travels with the hash, so raising PBKDF2_ITERATIONS later
    does not invalidate existing passwords — old hashes still verify against the
    count they were created with.
    """
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(derived).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_b64, derived_b64 = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(derived_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except Exception:
        # A malformed stored hash is a failed login, never a 500.
        return False


def token_hash(token: str) -> str:
    """Hash a session token for storage.

    Plain SHA-256 with no salt is deliberate here: the token is 48 random bytes,
    so there is nothing to brute-force, and the lookup has to be a single indexed
    query on an exact value.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def sign_flash(message: str, category: str) -> str:
    """Sign a flash message so it cannot be forged through the URL.

    Flash text is carried in the query string across a redirect, which means
    anything in the address bar would otherwise be rendered on our own page. An
    attacker could send someone a link reading "Your account was suspended,
    contact ..." — escaped, so not XSS, but a convincing phishing page on a
    domain the reader already trusts. Only messages this server generated carry a
    valid signature.
    """
    payload = f"{message}\x1f{category}".encode()
    return hmac.new(SECRET_KEY, payload, hashlib.sha256).hexdigest()[:32]


def verify_flash(message: str, category: str, signature: str) -> bool:
    return hmac.compare_digest(signature, sign_flash(message, category))
