"""Test fixtures.

Tests run against PostgreSQL when TEST_DATABASE_URL is set (CI does this), otherwise SQLite.
    TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/reeldm_test pytest
"""

import os
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.config import Settings, normalize_database_url
from app.instagram import InstagramClient
from app.main import create_app
from app.models import Base

GRAPH = "https://graph.instagram.com/v23.0"
IG_USER_ID = "17841400000000001"
APP_SCOPED_ID = "9876543210"


@pytest.fixture
def database_url(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        return f"sqlite:///{tmp_path / 'test.db'}"
    url = normalize_database_url(url)
    engine = create_engine(url)
    Base.metadata.drop_all(engine)  # fresh tables for every test
    engine.dispose()
    return url


@pytest.fixture
def settings(database_url, tmp_path):
    return Settings(
        base_url="https://reeldm.test",
        ig_app_id="app-id",
        ig_app_secret="app-secret",
        webhook_verify_token="verify-me",
        session_secret="session-secret",
        token_encryption_key=Fernet.generate_key().decode(),
        database_url=database_url,
        frontend_dist=tmp_path / "no-frontend",
    )


@pytest.fixture
def ig_mock():
    """Fake Instagram API. Unmocked calls fail the test. Only the Instagram client uses it,
    so the TestClient's own requests to the app are unaffected."""
    return respx.MockRouter(assert_all_called=False, assert_all_mocked=True)


@pytest.fixture
def app(settings, ig_mock):
    ig = InstagramClient(settings, http=httpx.Client(transport=httpx.MockTransport(ig_mock.handler)))
    return create_app(settings, ig=ig, run_background_jobs=False)


@pytest.fixture
def client(app):
    with TestClient(app, base_url="https://reeldm.test") as c:
        yield c


@pytest.fixture
def ctx(app):
    return app.state.ctx


def mock_login(ig_mock, *, token="long-token", user_id=IG_USER_ID, username="creator", subscribe_ok=True):
    ig_mock.post("https://api.instagram.com/oauth/access_token").respond(
        json={"access_token": "short-token", "user_id": user_id}
    )
    ig_mock.get("https://graph.instagram.com/access_token").respond(
        json={"access_token": token, "token_type": "bearer", "expires_in": 5184000}
    )
    ig_mock.get(f"{GRAPH}/me").respond(
        json={
            "id": APP_SCOPED_ID,
            "user_id": user_id,
            "username": username,
            "name": "Creator Name",
            "profile_picture_url": "https://cdn.test/pic.jpg",
            "account_type": "MEDIA_CREATOR",
        }
    )
    if subscribe_ok:
        ig_mock.post(f"{GRAPH}/me/subscribed_apps").respond(json={"success": True})
    else:
        ig_mock.post(f"{GRAPH}/me/subscribed_apps").respond(
            400, json={"error": {"message": "Missing permission", "code": 10}}
        )


def login(client, ig_mock, **kwargs):
    mock_login(ig_mock, **kwargs)
    start = client.get("/auth/instagram", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    return client.get(f"/auth/instagram/callback?code=the-code%23_&state={state}", follow_redirects=False)


@pytest.fixture
def logged_in(client, ig_mock):
    res = login(client, ig_mock)
    assert res.status_code == 303
    return client


def make_rule(client, **fields):
    body = {"keywords": "link", "dm_message": "Hi {username}! https://example.com/guide", **fields}
    res = client.post("/api/rules", json=body)
    assert res.status_code == 201, res.text
    return res.json()
