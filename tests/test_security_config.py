import base64
import hashlib
import hmac
import json

import pytest
from cryptography.fernet import Fernet

from app.config import ConfigError, Settings, normalize_database_url
from app.security import TokenCipher, parse_signed_request, verify_webhook_signature


def signed_request(secret: str, data: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=") + "." + payload


def test_token_cipher_round_trip_and_wrong_key():
    cipher = TokenCipher(Fernet.generate_key().decode())
    encrypted = cipher.encrypt("secret-token")
    assert "secret-token" not in encrypted
    assert cipher.decrypt(encrypted) == "secret-token"
    with pytest.raises(ValueError):
        TokenCipher(Fernet.generate_key().decode()).decrypt(encrypted)


def test_webhook_signature():
    body = b'{"a":1}'
    good = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature("s3cret", body, good)
    assert not verify_webhook_signature("s3cret", body + b" ", good)
    assert not verify_webhook_signature("s3cret", body, None)
    assert not verify_webhook_signature("s3cret", body, "sha1=abc")


def test_signed_request():
    req = signed_request("s3cret", {"user_id": "42", "algorithm": "HMAC-SHA256"})
    assert parse_signed_request("s3cret", req)["user_id"] == "42"
    assert parse_signed_request("other", req) is None
    assert parse_signed_request("s3cret", "garbage") is None


def test_normalize_database_url():
    assert normalize_database_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url("sqlite:///x.db") == "sqlite:///x.db"


def test_settings_from_env():
    env = {
        "BASE_URL": "https://x.test/",
        "IG_APP_ID": "1",
        "IG_APP_SECRET": "2",
        "WEBHOOK_VERIFY_TOKEN": "3",
        "SESSION_SECRET": "4",
        "TOKEN_ENCRYPTION_KEY": "5",
        "DATABASE_URL": "postgres://u@h/db",
    }
    s = Settings.from_env(env)
    assert s.redirect_uri == "https://x.test/auth/instagram/callback"
    assert s.cookie_secure
    assert s.database_url.startswith("postgresql+psycopg://")
    with pytest.raises(ConfigError, match="IG_APP_SECRET"):
        Settings.from_env({**env, "IG_APP_SECRET": ""})
