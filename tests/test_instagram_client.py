import httpx
import pytest

from app.config import Settings
from app.instagram import InstagramClient, InstagramError

UNSUPPORTED = {"error": {"message": "Unsupported request - method type: get", "type": "IGApiException", "code": 100}}


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


def test_long_lived_token_uses_documented_get():
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path, req.url.params["grant_type"]))
        return httpx.Response(200, json={"access_token": "long", "expires_in": 5184000})

    assert _client(handler).get_long_lived_token("short")["access_token"] == "long"
    assert calls == [("GET", "/access_token", "ig_exchange_token")]


def test_unsupported_request_is_recognised():
    client = _client(lambda req: httpx.Response(400, json=UNSUPPORTED))
    with pytest.raises(InstagramError) as info:
        client.get_long_lived_token("short")
    assert info.value.is_unsupported_request
    assert info.value.error["type"] == "IGApiException"


def test_other_errors_are_not_unsupported_request():
    body = {"error": {"message": "Error validating client secret", "type": "OAuthException", "code": 101}}
    with pytest.raises(InstagramError) as info:
        _client(lambda req: httpx.Response(400, json=body)).get_long_lived_token("short")
    assert not info.value.is_unsupported_request
