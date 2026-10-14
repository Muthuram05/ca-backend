"""In-memory stand-in for InstagramClient, used by the end-to-end browser tests."""

from urllib.parse import urlencode

from app.instagram import InstagramError

FAKE_IG_USER_ID = "17841499999999999"


class FakeInstagram:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.sent_dms: list[dict] = []
        self.public_replies: list[dict] = []
        self.media = [
            {
                "id": f"reel{i}",
                "caption": caption,
                "media_type": "VIDEO",
                "media_product_type": "REELS",
                "thumbnail_url": f"{base_url}/favicon.svg",
                "timestamp": f"2026-10-0{i}T10:00:00+0000",
            }
            for i, caption in enumerate(["Free budget template", "Morning routine", "Studio tour"], start=1)
        ]

    def authorize_url(self, state: str) -> str:
        # Skip Instagram entirely: bounce straight back to our callback
        return f"{self.base_url}/auth/instagram/callback?{urlencode({'code': 'fake-code', 'state': state})}"

    def exchange_code(self, code: str) -> dict:
        if code != "fake-code":
            raise InstagramError("Invalid code")
        return {"access_token": "short", "user_id": FAKE_IG_USER_ID}

    def get_long_lived_token(self, short_token: str) -> dict:
        return {"access_token": "fake-long-token", "expires_in": 60 * 24 * 3600}

    def refresh_token(self, long_token: str) -> dict:
        return {"access_token": "fake-long-token", "expires_in": 60 * 24 * 3600}

    def get_profile(self, token: str) -> dict:
        return {"id": "555", "user_id": FAKE_IG_USER_ID, "username": "demo.creator", "name": "Demo Creator"}

    def subscribe_to_webhooks(self, token: str) -> dict:
        return {"success": True}

    def list_media(self, token: str, limit: int = 30) -> list[dict]:
        return self.media

    def send_private_reply(self, token: str, ig_user_id: str, comment_id: str, text: str) -> dict:
        self.sent_dms.append({"comment_id": comment_id, "text": text})
        return {"message_id": f"m-{comment_id}"}

    def reply_to_comment(self, token: str, comment_id: str, text: str) -> dict:
        self.public_replies.append({"comment_id": comment_id, "text": text})
        return {"id": f"r-{comment_id}"}
