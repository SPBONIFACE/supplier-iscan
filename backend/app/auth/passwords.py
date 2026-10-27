"""Password hashing with Argon2id (spec, Security model). Passwords are never stored or logged."""

import secrets
from functools import cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2-cffi's defaults: Argon2id, RFC 9106 low-memory profile.
_hasher = PasswordHasher()


def normalise_email(email: str) -> str:
    """Emails are stored and compared trimmed and lower-cased."""
    return email.strip().lower()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


@cache
def _dummy_hash() -> str:
    return _hasher.hash(secrets.token_urlsafe(32))


def spend_verification_time(password: str) -> None:
    """Verify against a throwaway hash: an unknown email takes as long as a wrong password."""
    verify_password(_dummy_hash(), password)
