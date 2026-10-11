"""The web login's secrets: scrypt hash and TOTP (the web app reads the same formats)."""

import base64

from app import auth


def test_password_hash_round_trip_and_no_dollar_sign():
    stored = auth.hash_password("correct horse battery")
    assert stored.startswith("scrypt:16384:8:1:")
    assert "$" not in stored  # Docker Compose would read $ in .env as a variable
    assert auth.verify_password("correct horse battery", stored)
    assert not auth.verify_password("correct horse batterY", stored)
    assert not auth.verify_password("x", "not-a-hash")


def test_same_password_different_salt():
    assert auth.hash_password("abcdefghijk") != auth.hash_password("abcdefghijk")


def test_totp_matches_rfc_6238():
    # RFC 6238 appendix B, SHA1 key "12345678901234567890".
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert auth.totp(secret, at=59, digits=8) == "94287082"
    assert auth.totp(secret, at=1111111109, digits=8) == "07081804"
    assert auth.totp(secret, at=59) == "287082"


def test_new_secret_and_uri():
    secret = auth.new_totp_secret()
    assert len(secret) == 32 and "=" not in secret
    assert len(auth.totp(secret)) == 6
    uri = auth.otpauth_uri(secret)
    assert uri.startswith("otpauth://totp/Jeron:Jeron?secret=") and "period=30" in uri
