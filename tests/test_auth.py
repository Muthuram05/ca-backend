import logging
from urllib.parse import parse_qs, urlparse

from app.models import Account
from conftest import APP_SCOPED_ID, IG_USER_ID, login, make_rule
from test_security_config import signed_request


def test_login_redirects_to_facebook_with_config_and_state(client):
    # Facebook Login for Business: the configuration carries the permissions,
    # so the dialog takes a config_id instead of a scope list.
    res = client.get("/auth/instagram", follow_redirects=False)
    assert res.status_code == 303
    url = urlparse(res.headers["location"])
    params = parse_qs(url.query)
    assert url.netloc == "www.facebook.com"
    assert url.path == "/dialog/oauth"
    assert params["client_id"] == ["app-id"]
    assert params["config_id"] == ["config-id"]
    assert params["redirect_uri"] == ["https://reeldm.test/auth/instagram/callback"]
    assert "scope" not in params
    assert len(params["state"][0]) > 20


def test_successful_login_stores_encrypted_token_and_logs_in(client, ig_mock, ctx):
    res = login(client, ig_mock)
    assert res.status_code == 303
    assert res.headers["location"] == "/"

    # Code is sent without Instagram's trailing "#_"
    exchange = ig_mock.calls[0].request
    assert "code=the-code" in str(exchange.url)

    me = client.get("/api/me").json()
    assert me["username"] == "creator"
    assert me["webhook_subscribed"] is True

    with ctx.sessions() as db:
        account = db.get(Account, IG_USER_ID)
        # Facebook Login returns a single id for the account, so there is no
        # separate app-scoped id to store.
        assert account.app_scoped_id is None
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


def test_callback_keeps_instagram_error_detail_out_of_the_url(client, ig_mock, caplog):
    ig_mock.get("https://graph.facebook.com/v23.0/oauth/access_token").respond(
        400, json={"error_type": "OAuthException", "code": 400, "error_message": "Invalid code"}
    )
    start = client.get("/auth/instagram", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    with caplog.at_level(logging.WARNING, logger="reeldm"):
        res = client.get(f"/auth/instagram/callback?code=bad&state={state}", follow_redirects=False)

    location = res.headers["location"]
    assert "error=" in location
    # A failed discovery reports every probe it tried, naming the business and system-user
    # ids. The person logging in gets a plain message; the detail goes to the logs.
    assert "Invalid" not in location
    assert "Invalid code" in caplog.text
    assert client.get("/api/me").status_code == 401


def test_logout(logged_in):
    assert logged_in.post("/auth/logout").status_code == 204
    assert logged_in.get("/api/me").status_code == 401


def test_data_deletion_callback_removes_everything(logged_in, ctx):
    make_rule(logged_in)
    # Facebook Login returns one id for the account, so that is what Meta sends
    req = signed_request("app-secret", {"user_id": IG_USER_ID})
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
