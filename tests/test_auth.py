from urllib.parse import parse_qs, urlparse

from app.models import Account
from conftest import APP_SCOPED_ID, IG_USER_ID, login, make_rule
from test_security_config import signed_request


def test_login_redirects_to_instagram_with_scopes_and_state(client):
    res = client.get("/auth/instagram", follow_redirects=False)
    assert res.status_code == 303
    url = urlparse(res.headers["location"])
    params = parse_qs(url.query)
    assert url.netloc == "www.instagram.com"
    assert params["client_id"] == ["app-id"]
    assert params["redirect_uri"] == ["https://reeldm.test/auth/instagram/callback"]
    assert "instagram_business_manage_messages" in params["scope"][0]
    assert len(params["state"][0]) > 20


def test_successful_login_stores_encrypted_token_and_logs_in(client, ig_mock, ctx):
    res = login(client, ig_mock)
    assert res.status_code == 303
    assert res.headers["location"] == "/"

    # Code is sent without Instagram's trailing "#_"
    exchange = ig_mock.calls[0].request
    assert b"code=the-code&" in exchange.content or exchange.content.endswith(b"code=the-code")

    me = client.get("/api/me").json()
    assert me["username"] == "creator"
    assert me["webhook_subscribed"] is True

    with ctx.sessions() as db:
        account = db.get(Account, IG_USER_ID)
        assert account.app_scoped_id == APP_SCOPED_ID
        assert "long-token" not in account.access_token_encrypted
        assert ctx.cipher.decrypt(account.access_token_encrypted) == "long-token"


def test_login_again_updates_the_same_account(client, ig_mock, ctx):
    login(client, ig_mock, token="first")
    ig_mock.routes.clear()
    login(client, ig_mock, token="second", username="renamed")
    with ctx.sessions() as db:
        accounts = db.query(Account).all()
        assert len(accounts) == 1
        assert accounts[0].username == "renamed"
        assert ctx.cipher.decrypt(accounts[0].access_token_encrypted) == "second"


def test_webhook_subscription_failure_still_logs_in_with_warning(client, ig_mock):
    res = login(client, ig_mock, subscribe_ok=False)
    assert "warning=" in res.headers["location"]
    me = client.get("/api/me").json()
    assert me["webhook_subscribed"] is False
    assert "Missing permission" in me["webhook_error"]


def test_callback_rejects_wrong_state(client, ig_mock):
    client.get("/auth/instagram", follow_redirects=False)
    res = client.get("/auth/instagram/callback?code=abc&state=forged", follow_redirects=False)
    assert "error=" in res.headers["location"]
    assert client.get("/api/me").status_code == 401
    assert not ig_mock.calls


def test_callback_handles_user_cancel(client):
    res = client.get("/auth/instagram/callback?error=access_denied&error_description=denied", follow_redirects=False)
    assert "cancelled" in res.headers["location"]


def test_callback_handles_instagram_error(client, ig_mock):
    ig_mock.post("https://api.instagram.com/oauth/access_token").respond(
        400, json={"error_type": "OAuthException", "code": 400, "error_message": "Invalid code"}
    )
    start = client.get("/auth/instagram", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    res = client.get(f"/auth/instagram/callback?code=bad&state={state}", follow_redirects=False)
    assert "Invalid%20code" in res.headers["location"]
    assert client.get("/api/me").status_code == 401


def test_logout(logged_in):
    assert logged_in.post("/auth/logout").status_code == 204
    assert logged_in.get("/api/me").status_code == 401


def test_data_deletion_callback_removes_everything(logged_in, ctx):
    make_rule(logged_in)
    # Meta may identify the user by the app-scoped id
    req = signed_request("app-secret", {"user_id": APP_SCOPED_ID})
    res = logged_in.post("/auth/instagram/data-deletion", data={"signed_request": req})
    assert res.status_code == 200
    body = res.json()
    assert body["url"].startswith("https://reeldm.test/deletion?code=")
    assert body["confirmation_code"] in body["url"]
    with ctx.sessions() as db:
        assert db.get(Account, IG_USER_ID) is None
    assert logged_in.get("/api/me").status_code == 401


def test_deauthorize_callback(logged_in, ctx):
    req = signed_request("app-secret", {"user_id": IG_USER_ID})
    assert logged_in.post("/auth/instagram/deauthorize", data={"signed_request": req}).status_code == 200
    with ctx.sessions() as db:
        assert db.get(Account, IG_USER_ID) is None


def test_deletion_callbacks_reject_bad_signature(client):
    req = signed_request("wrong-secret", {"user_id": IG_USER_ID})
    assert client.post("/auth/instagram/data-deletion", data={"signed_request": req}).status_code == 400
    assert client.post("/auth/instagram/deauthorize", data={"signed_request": "x.y"}).status_code == 400
