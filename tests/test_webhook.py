import hashlib
import hmac
import json
from datetime import timedelta

import pytest

from app.models import Account, Activity, ProcessedComment, Rule, utcnow
from app.services import cleanup_old_rows, refresh_expiring_tokens
from conftest import GRAPH, IG_USER_ID, make_rule


def payload(comment_id="c1", text="LINK please", from_id="999", username="fan", media_id="reel1", account=IG_USER_ID):
    return {
        "object": "instagram",
        "entry": [
            {
                "id": account,
                "time": 1,
                "changes": [
                    {
                        "field": "comments",
                        "value": {
                            "id": comment_id,
                            "text": text,
                            "from": {"id": from_id, "username": username},
                            "media": {"id": media_id, "media_product_type": "REELS"},
                        },
                    }
                ],
            }
        ],
    }


def post_event(client, data, secret="app-secret"):
    body = json.dumps(data).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/webhook", content=body, headers={"x-hub-signature-256": sig, "content-type": "application/json"})


@pytest.fixture
def dm_route(ig_mock):
    return ig_mock.post(f"{GRAPH}/{IG_USER_ID}/messages").respond(json={"recipient_id": "999", "message_id": "m1"})


def reply_route(ig_mock, comment_id="c1", **kwargs):
    return ig_mock.post(f"{GRAPH}/{comment_id}/replies").respond(**(kwargs or {"json": {"id": "r1"}}))


def activity(ctx):
    with ctx.sessions() as db:
        return db.query(Activity).order_by(Activity.id).all()


def test_verification_handshake(client):
    ok = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "123"})
    assert (ok.status_code, ok.text) == (200, "123")
    bad = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "123"})
    assert bad.status_code == 403


def test_rejects_bad_signature_and_bad_json(client):
    assert post_event(client, payload(), secret="wrong").status_code == 401
    assert client.post("/webhook", content=b"{}").status_code == 401
    body = b"not json"
    sig = "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()
    assert client.post("/webhook", content=body, headers={"x-hub-signature-256": sig}).status_code == 400


def test_matching_comment_sends_dm_and_public_reply(logged_in, ig_mock, ctx, dm_route):
    rule = make_rule(logged_in, public_reply="Sent! Check your DMs {username}")
    reply = reply_route(ig_mock)

    assert post_event(logged_in, payload()).status_code == 200

    dm = dm_route.calls.last.request
    assert dm.headers["authorization"] == "Bearer long-token"
    assert json.loads(dm.content) == {
        "recipient": {"comment_id": "c1"},
        "message": {"text": "Hi @fan! https://example.com/guide"},
    }
    assert reply.calls.last.request.url.params["message"] == "Sent! Check your DMs @fan"

    [entry] = activity(ctx)
    assert (entry.status, entry.username, entry.comment_text, entry.rule_id) == ("sent", "fan", "LINK please", rule["id"])
    assert entry.error is None
    assert logged_in.get("/api/rules").json()[0]["sent_count"] == 1


def test_duplicate_delivery_dms_only_once(logged_in, ctx, dm_route):
    make_rule(logged_in)
    post_event(logged_in, payload())
    post_event(logged_in, payload())
    assert dm_route.call_count == 1
    assert len(activity(ctx)) == 1


def test_ignores_non_matching_and_own_comments_and_unknown_accounts(logged_in, ctx, dm_route):
    make_rule(logged_in)
    post_event(logged_in, payload(comment_id="c2", text="great video"))
    post_event(logged_in, payload(comment_id="c3", text="link", from_id=IG_USER_ID))
    post_event(logged_in, payload(comment_id="c4", text="link", account="someone-else"))
    other = payload(comment_id="c5")
    other["entry"][0]["changes"][0]["field"] = "mentions"
    post_event(logged_in, other)
    assert dm_route.call_count == 0
    assert activity(ctx) == []
    with ctx.sessions() as db:
        assert db.query(ProcessedComment).count() == 0


def test_paused_rule_does_nothing(logged_in, ctx, dm_route):
    rule = make_rule(logged_in)
    logged_in.patch(f"/api/rules/{rule['id']}", json={"enabled": False})
    post_event(logged_in, payload())
    assert dm_route.call_count == 0


def test_reel_specific_rule_wins(logged_in, ctx, dm_route):
    make_rule(logged_in, dm_message="generic")
    make_rule(logged_in, dm_message="reel one link", media_id="reel1")
    post_event(logged_in, payload(comment_id="a", media_id="reel1"))
    post_event(logged_in, payload(comment_id="b", media_id="reel2"))
    texts = [json.loads(c.request.content)["message"]["text"] for c in dm_route.calls]
    assert texts == ["reel one link", "generic"]


def test_failed_dm_is_logged_and_not_counted(logged_in, ig_mock, ctx):
    make_rule(logged_in, public_reply="Check DMs")
    ig_mock.post(f"{GRAPH}/{IG_USER_ID}/messages").respond(
        400, json={"error": {"message": "This message is sent outside of allowed window."}}
    )
    reply = reply_route(ig_mock)
    post_event(logged_in, payload())
    [entry] = activity(ctx)
    assert entry.status == "failed"
    assert "allowed window" in entry.error
    assert reply.call_count == 0  # don't say "check your DMs" if the DM failed
    assert logged_in.get("/api/rules").json()[0]["sent_count"] == 0


def test_public_reply_failure_still_counts_dm(logged_in, ig_mock, ctx, dm_route):
    make_rule(logged_in, public_reply="Check DMs")
    reply_route(ig_mock, status_code=400, json={"error": {"message": "Comment deleted"}})
    post_event(logged_in, payload())
    [entry] = activity(ctx)
    assert entry.status == "sent"
    assert "public reply failed: Comment deleted" in entry.error


def test_one_event_with_many_comments(logged_in, ctx, dm_route):
    make_rule(logged_in)
    data = payload()
    data["entry"][0]["changes"] += payload(comment_id="c2", username="fan2")["entry"][0]["changes"]
    post_event(logged_in, data)
    assert dm_route.call_count == 2


# ---------- Maintenance jobs ----------


def test_refresh_expiring_tokens(logged_in, ig_mock, ctx):
    now = utcnow()
    with ctx.sessions() as db:
        db.get(Account, IG_USER_ID).token_expires_at = now + timedelta(days=3)
        db.commit()
    route = ig_mock.get("https://graph.instagram.com/refresh_access_token").respond(
        json={"access_token": "refreshed", "expires_in": 5184000}
    )
    assert refresh_expiring_tokens(ctx, now) == 1
    assert route.calls.last.request.url.params["access_token"] == "long-token"
    with ctx.sessions() as db:
        account = db.get(Account, IG_USER_ID)
        assert ctx.cipher.decrypt(account.access_token_encrypted) == "refreshed"
    # Fresh token is not refreshed again
    assert refresh_expiring_tokens(ctx, now) == 0


def test_cleanup_old_rows(logged_in, ctx):
    old = utcnow() - timedelta(days=100)
    with ctx.sessions() as db:
        db.add_all(
            [
                ProcessedComment(comment_id="old", ig_user_id=IG_USER_ID, created_at=old),
                ProcessedComment(comment_id="new", ig_user_id=IG_USER_ID),
                Activity(ig_user_id=IG_USER_ID, comment_id="old", status="sent", created_at=old),
                Activity(ig_user_id=IG_USER_ID, comment_id="new", status="sent"),
            ]
        )
        db.commit()
    cleanup_old_rows(ctx)
    with ctx.sessions() as db:
        assert [p.comment_id for p in db.query(ProcessedComment)] == ["new"]
        assert [a.comment_id for a in db.query(Activity)] == ["new"]
        assert db.query(Rule).count() == 0
