from app.auth.passwords import (
    hash_password,
    needs_rehash,
    normalise_email,
    spend_verification_time,
    verify_password,
)
from app.auth.sessions import hash_token, new_token


def test_hash_is_argon2id_and_salted() -> None:
    first, second = hash_password("same password"), hash_password("same password")

    assert first.startswith("$argon2id$")
    assert first != second
    assert "same password" not in first


def test_verify_accepts_the_password_and_refuses_others() -> None:
    password_hash = hash_password("right")

    assert verify_password(password_hash, "right")
    assert not verify_password(password_hash, "wrong")
    assert not verify_password(password_hash, "")


def test_verify_refuses_a_malformed_hash() -> None:
    assert not verify_password("not-a-hash", "anything")


def test_fresh_hash_needs_no_rehash() -> None:
    assert not needs_rehash(hash_password("x"))


def test_dummy_verification_runs_without_error() -> None:
    spend_verification_time("anything")


def test_email_normalisation() -> None:
    assert normalise_email("  Ann.Smith@Example.COM ") == "ann.smith@example.com"


def test_session_tokens_are_random_and_hashed() -> None:
    first, second = new_token(), new_token()

    assert first != second
    assert len(first) >= 43  # 32 random bytes
    assert len(hash_token(first)) == 64
    assert hash_token(first) != first
