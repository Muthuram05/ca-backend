"""Client for the "Instagram API with Instagram Login".

Docs: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login
"""

import logging
from urllib.parse import urlencode

import httpx

from .config import Settings

log = logging.getLogger("reeldm")

SCOPES = [
    "instagram_business_basic",
    "instagram_business_manage_comments",
    "instagram_business_manage_messages",
]


class InstagramError(Exception):
    def __init__(self, message: str, status: int | None = None, body: dict | None = None):
        super().__init__(message)
        self.status = status
        self.body = body or {}

    @property
    def error(self) -> dict:
        err = self.body.get("error") if isinstance(self.body, dict) else None
        return err if isinstance(err, dict) else {}

    @property
    def is_unsupported_request(self) -> bool:
        return self.error.get("code") == 100 and "Unsupported request" in str(self)


class InstagramClient:
    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        self.settings = settings
        self.http = http or httpx.Client(timeout=15)
        self.graph = f"https://graph.instagram.com/{settings.graph_version}"

    def _request(self, method: str, url: str, **kwargs) -> dict:
        try:
            res = self.http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise InstagramError(f"Could not reach Instagram: {exc}") from exc
        try:
            body = res.json() if res.content else {}
        except ValueError:
            body = {"raw": res.text}
        if res.is_error or (isinstance(body, dict) and "error" in body):
            err = body.get("error") if isinstance(body, dict) else None
            message = (
                (err.get("message") if isinstance(err, dict) else err)
                or body.get("error_message")
                or f"Instagram API error (HTTP {res.status_code})"
            )
            raise InstagramError(str(message), res.status_code, body)
        return body

    # ---------- Login ----------

    def authorize_url(self, state: str) -> str:
        params = {
            "client_id": self.settings.ig_app_id,
            "redirect_uri": self.settings.redirect_uri,
            "response_type": "code",
            "scope": ",".join(SCOPES),
            "state": state,
        }
        return f"https://www.instagram.com/oauth/authorize?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        """Authorization code -> short-lived token (valid 1 hour)."""
        return self._request(
            "POST",
            "https://api.instagram.com/oauth/access_token",
            data={
                "client_id": self.settings.ig_app_id,
                "client_secret": self.settings.ig_app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": self.settings.redirect_uri,
                "code": code,
            },
        )

    def get_long_lived_token(self, short_token: str) -> dict:
        """Short-lived -> long-lived token (valid 60 days). Returns access_token, expires_in.

        Business Login for Instagram can already hand out a long-lived token; Instagram then
        rejects this exchange with code 100 "Unsupported request". Callers handle that case
        (see services.connect_account); this method only logs the details, never the secret.
        """
        try:
            return self._request(
                "GET",
                "https://graph.instagram.com/access_token",
                params={
                    "grant_type": "ig_exchange_token",
                    "client_secret": self.settings.ig_app_secret,
                    "access_token": short_token,
                },
            )
        except InstagramError as exc:
            err = exc.error
            log.warning(
                "Long-lived token exchange failed: HTTP %s, message=%r, type=%s, code=%s, subcode=%s, fbtrace_id=%s",
                exc.status, str(exc), err.get("type"), err.get("code"), err.get("error_subcode"), err.get("fbtrace_id"),
            )
            raise

    def refresh_token(self, long_token: str) -> dict:
        """Extends a long-lived token by another 60 days (token must be at least 24h old)."""
        return self._request(
            "GET",
            "https://graph.instagram.com/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": long_token},
        )

    # ---------- Account ----------

    def get_profile(self, token: str) -> dict:
        try:
            return self._get_profile(token)
        except InstagramError as exc:
            err = exc.error
            log.warning(
                "GET /me failed: HTTP %s, message=%r, type=%s, code=%s, subcode=%s, fbtrace_id=%s",
                exc.status, str(exc), err.get("type"), err.get("code"), err.get("error_subcode"), err.get("fbtrace_id"),
            )
            raise

    def _get_profile(self, token: str) -> dict:
        return self._request(
            "GET",
            f"{self.graph}/me",
            params={
                "fields": "id,user_id,username,name,profile_picture_url,account_type",
                "access_token": token,
            },
        )

    def subscribe_to_webhooks(self, token: str) -> dict:
        """Ask Instagram to send this account's comment events to our webhook."""
        return self._request(
            "POST",
            f"{self.graph}/me/subscribed_apps",
            params={"subscribed_fields": "comments", "access_token": token},
        )

    def list_media(self, token: str, limit: int = 30) -> list[dict]:
        body = self._request(
            "GET",
            f"{self.graph}/me/media",
            params={
                "fields": "id,caption,media_type,media_product_type,thumbnail_url,media_url,permalink,timestamp",
                "limit": limit,
                "access_token": token,
            },
        )
        return body.get("data", [])

    # ---------- Messaging ----------

    def send_private_reply(self, token: str, ig_user_id: str, comment_id: str, text: str) -> dict:
        """DM the person who left a comment. One per comment, within 7 days of it being posted."""
        return self._request(
            "POST",
            f"{self.graph}/{ig_user_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"recipient": {"comment_id": comment_id}, "message": {"text": text}},
        )

    def reply_to_comment(self, token: str, comment_id: str, text: str) -> dict:
        """Public reply under the comment, e.g. "Check your DMs!"."""
        return self._request(
            "POST",
            f"{self.graph}/{comment_id}/replies",
            params={"message": text, "access_token": token},
        )
