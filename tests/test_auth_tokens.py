"""Unit tests for JWT decoding hardening. No database required."""
import base64
import json

from app.core.auth import create_token, decode_token


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def test_decode_token_round_trip():
    token = create_token("u1", "alice", False)
    payload = decode_token(token)
    assert payload["sub"] == "alice"
    assert payload["user_id"] == "u1"


def test_decode_token_rejects_tampered_signature():
    token = create_token("u1", "alice", True)
    header, body, sig = token.split(".")
    flipped = ("A" if sig[0] != "A" else "B") + sig[1:]
    assert decode_token(f"{header}.{body}.{flipped}") is None


def test_decode_token_rejects_non_canonical_signature_segment():
    token = create_token("u1", "alice", False)
    assert decode_token(token + "!!!!") is None


def test_decode_token_survives_deeply_nested_header():
    """A crafted header must yield None, not an uncaught RecursionError (-> HTTP 500).

    Regression for PyJWT GHSA-8wjv-2p76-3863 (fixed in 2.14.0).
    """
    depth = 100_000
    header = _b64(b"[" * depth + b"]" * depth)
    body = _b64(json.dumps({"sub": "x"}).encode())
    assert decode_token(f"{header}.{body}.{_b64(b'sig')}") is None
