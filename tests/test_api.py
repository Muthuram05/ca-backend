import pytest

from app.models import Account, Activity, Rule
from conftest import GRAPH, IG_USER_ID, login, make_rule


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/me"),
        ("get", "/api/media"),
        ("get", "/api/rules"),
        ("post", "/api/rules"),
        ("post", "/api/rules/test"),
        ("get", "/api/activity"),
        ("delete", "/api/account"),
    ],
)
def test_requires_login(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_create_list_update_toggle_delete_rule(logged_in):
    rule = make_rule(
        logged_in,
        name="Free guide",
        keywords="Link, GUIDE!",
        media_id="reel1",
        media_label="Reel · guide",
        public_reply="Check your DMs!",
    )
    assert rule["keywords"] == ["link", "guide"]
    assert rule["enabled"] is True
    assert rule["sent_count"] == 0

    assert [r["id"] for r in logged_in.get("/api/rules").json()] == [rule["id"]]

    updated = logged_in.put(
        f"/api/rules/{rule['id']}", json={"keywords": ["info"], "dm_message": "New message", "match_type": "exact"}
    ).json()
    assert updated["keywords"] == ["info"]
    assert updated["match_type"] == "exact"
    assert updated["media_id"] is None
    assert updated["name"] == "info"  # defaults to keywords when blank

    assert logged_in.patch(f"/api/rules/{rule['id']}", json={"enabled": False}).json()["enabled"] is False

    assert logged_in.delete(f"/api/rules/{rule['id']}").status_code == 204
    assert logged_in.get("/api/rules").json() == []
    assert logged_in.delete(f"/api/rules/{rule['id']}").status_code == 404


@pytest.mark.parametrize(
    "body,message",
    [
        ({"keywords": "", "dm_message": "hi"}, "at least one keyword"),
        ({"keywords": "link", "dm_message": "   "}, "can't be empty"),
        ({"keywords": "link", "dm_message": "x" * 1001}, "1000"),
        ({"keywords": "link", "dm_message": "hi", "match_type": "regex"}, "match_type"),
        ({"keywords": "link"}, "dm_message"),
    ],
)
def test_rule_validation(logged_in, body, message):
    res = logged_in.post("/api/rules", json=body)
    assert res.status_code == 422
    assert message in res.json()["detail"]


def test_any_match_rule_needs_no_keywords(logged_in):
    rule = make_rule(logged_in, keywords="", match_type="any")
    assert rule["name"] == "Any comment"


def test_cannot_touch_another_accounts_rules(logged_in, ig_mock, ctx):
    rule = make_rule(logged_in)
    logged_in.post("/auth/logout")
    ig_mock.routes.clear()
    login(logged_in, ig_mock, user_id="17841400000000002", username="someone_else")

    assert logged_in.get("/api/rules").json() == []
    assert logged_in.put(f"/api/rules/{rule['id']}", json={"keywords": "x", "dm_message": "x"}).status_code == 404
    assert logged_in.patch(f"/api/rules/{rule['id']}", json={"enabled": False}).status_code == 404
    assert logged_in.delete(f"/api/rules/{rule['id']}").status_code == 404
    with ctx.sessions() as db:
        assert db.get(Rule, rule["id"]).enabled is True


def test_comment_tester(logged_in):
    make_rule(logged_in, public_reply="Sent, {username}!")
    hit = logged_in.post("/api/rules/test", json={"text": "LINK pls", "username": "sam"}).json()
    assert hit["matched"] is True
    assert hit["dm"] == "Hi @sam! https://example.com/guide"
    assert hit["public_reply"] == "Sent, @sam!"
    miss = logged_in.post("/api/rules/test", json={"text": "nice"}).json()
    assert miss == {"matched": False, "rule": None, "dm": None, "public_reply": None}


def test_media_list(logged_in, ig_mock):
    route = ig_mock.get(f"{GRAPH}/me/media").respond(
        json={"data": [{"id": "reel1", "media_product_type": "REELS", "timestamp": "2026-10-01T00:00:00+0000"}]}
    )
    assert logged_in.get("/api/media").json()[0]["id"] == "reel1"
    assert route.calls.last.request.url.params["access_token"] == "long-token"


def test_media_error_is_reported(logged_in, ig_mock):
    ig_mock.get(f"{GRAPH}/me/media").respond(400, json={"error": {"message": "Token expired"}})
    res = logged_in.get("/api/media")
    assert res.status_code == 502
    assert "Token expired" in res.json()["detail"]


def test_activity_newest_first_and_stats(logged_in, ctx):
    rule = make_rule(logged_in)
    with ctx.sessions() as db:
        for i, status in enumerate(["sent", "failed", "sent"]):
            db.add(Activity(ig_user_id=IG_USER_ID, rule_id=rule["id"], rule_name="r", comment_id=f"c{i}", status=status))
        db.get(Rule, rule["id"]).sent_count = 2
        db.commit()

    items = logged_in.get("/api/activity").json()
    assert [a["comment_id"] for a in items] == ["c2", "c1", "c0"]
    assert logged_in.get("/api/me").json()["stats"] == {"total_sent": 2, "sent_7d": 2, "failed_7d": 1}


def test_resubscribe(client, ig_mock):
    login(client, ig_mock, subscribe_ok=False)
    ig_mock.post(f"{GRAPH}/me/subscribed_apps").respond(json={"success": True})
    me = client.post("/api/account/resubscribe").json()
    assert me["webhook_subscribed"] is True
    assert me["webhook_error"] is None


def test_delete_account(logged_in, ctx):
    make_rule(logged_in)
    assert logged_in.delete("/api/account").status_code == 204
    assert logged_in.get("/api/me").status_code == 401
    with ctx.sessions() as db:
        assert db.get(Account, IG_USER_ID) is None
        assert db.query(Rule).count() == 0


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_unknown_api_path_is_404(client):
    assert client.get("/api/nope").status_code == 404
