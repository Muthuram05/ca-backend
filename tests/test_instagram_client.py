import httpx
import pytest

from app.config import Settings
from app.instagram import InstagramClient, InstagramError


def _settings() -> Settings:
    return Settings(
        base_url="https://example.test",
        ig_app_id="1",
        ig_app_secret="secret",
        webhook_verify_token="v",
        session_secret="s",
        token_encryption_key="k",
        database_url="sqlite://",
    )


def _client(handler) -> InstagramClient:
    return InstagramClient(_settings(), http=httpx.Client(transport=httpx.MockTransport(handler)))


UNSUPPORTED = {"error": {"message": "Unsupported request - method type: get", "type": "IGApiException", "code": 100}}


def test_long_lived_token_uses_documented_get_first():
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path))
        return httpx.Response(200, json={"access_token": "long", "expires_in": 5184000})

    assert _client(handler).get_long_lived_token("short")["access_token"] == "long"
    assert calls == [("GET", "/access_token")]


def test_long_lived_token_falls_back_when_get_is_rejected():
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path))
        if req.method == "POST":
            assert b"ig_exchange_token" in req.content
            return httpx.Response(200, json={"access_token": "long", "expires_in": 5184000})
        return httpx.Response(400, json=UNSUPPORTED)

    assert _client(handler).get_long_lived_token("short")["access_token"] == "long"
    assert calls == [("GET", "/access_token"), ("GET", "/v23.0/access_token"), ("POST", "/access_token")]


def test_long_lived_token_raises_when_every_attempt_fails():
    client = _client(lambda req: httpx.Response(400, json=UNSUPPORTED))
    with pytest.raises(InstagramError, match="Unsupported request"):
        client.get_long_lived_token("short")
