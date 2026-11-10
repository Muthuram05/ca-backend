"""Client for the "Instagram API with Facebook Login" (Unified login).

Meta stopped offering "API setup with Instagram login" to apps created from
late October 2026, so this app is configured as Facebook Login for Business:
login goes through facebook.com/dialog/oauth with a config_id, the token is a
system-user token that does not expire, and every call goes to
graph.facebook.com rather than graph.instagram.com.

Docs: https://developers.facebook.com/docs/facebook-login/facebook-login-for-business
"""

from urllib.parse import urlencode

import httpx

from .config import Settings

# The permissions the Facebook Login for Business configuration actually grants.
# The instagram_business_* names belong to Instagram Login and are rejected here.
SCOPES = [
    "instagram_basic",
    "instagram_manage_comments",
    "instagram_manage_messages",
]


class InstagramError(Exception):
    def __init__(self, message: str, status: int | None = None, body: dict | None = None):
        super().__init__(message)
        self.status = status
        self.body = body or {}


class InstagramClient:
    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        self.settings = settings
        self.http = http or httpx.Client(timeout=15)
        self.graph = f"https://graph.facebook.com/{settings.graph_version}"

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
        # config_id replaces scope: the configuration in the app dashboard decides
        # which permissions and business assets are requested.
        params = {
            "client_id": self.settings.ig_app_id,
            "config_id": self.settings.ig_config_id,
            "redirect_uri": self.settings.redirect_uri,
            "response_type": "code",
            "override_default_response_type": "true",
            "state": state,
        }
        return f"https://www.facebook.com/dialog/oauth?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        """Authorization code -> access token."""
        return self._request(
            "GET",
            f"{self.graph}/oauth/access_token",
            params={
                "client_id": self.settings.ig_app_id,
                "client_secret": self.settings.ig_app_secret,
                "redirect_uri": self.settings.redirect_uri,
                "code": code,
            },
        )

    def get_long_lived_token(self, short_token: str) -> dict:
        """Exchange for a long-lived token where the app issues one.

        This configuration issues a system-user token that never expires, in
        which case the exchange is unnecessary and may be refused; the original
        token is then returned unchanged with no expiry.
        """
        try:
            body = self._request(
                "GET",
                f"{self.graph}/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": self.settings.ig_app_id,
                    "client_secret": self.settings.ig_app_secret,
                    "fb_exchange_token": short_token,
                },
            )
        except InstagramError:
            return {"access_token": short_token, "expires_in": 0}
        body.setdefault("access_token", short_token)
        return body

    def refresh_token(self, long_token: str) -> dict:
        """System-user tokens do not expire, so there is nothing to refresh."""
        return {"access_token": long_token, "expires_in": 0}

    # ---------- Account ----------

    IG_FIELDS = "id,username,name,profile_picture_url"

    def _try(self, probes: list, path: str, token: str, **params) -> dict | None:
        """Run one discovery probe, recording the outcome instead of raising."""
        try:
            body = self._request("GET", f"{self.graph}/{path}", params={"access_token": token, **params})
        except InstagramError as exc:
            probes.append(f"{path} -> error: {exc}")
            return None
        probes.append(f"{path} -> {str(body)[:200]}")
        return body

    # The edges that can carry an Instagram account, newest naming first.
    BUSINESS_IG_EDGES = ("owned_instagram_accounts", "client_instagram_accounts", "instagram_accounts")

    def _business_account(self, probes: list, business_id: str, token: str) -> dict | None:
        for edge in self.BUSINESS_IG_EDGES:
            body = self._try(probes, f"{business_id}/{edge}", token, fields=self.IG_FIELDS)
            accounts = (body or {}).get("data") or []
            if accounts:
                return accounts[0]
        return None

    def get_profile(self, token: str) -> dict:
        """Find the Instagram account this token was granted.

        Facebook Login for Business hands back a token scoped to business assets
        rather than to the Instagram user, so the account has to be discovered,
        and which edge carries it depends on how the account was granted. The
        In practice only settings.ig_user_id gets there: the unified-login
        configuration can request Instagram permissions but not
        business_management, so me/businesses is refused and every edge on a
        named business returns (#200). The earlier probes are kept because they
        are the documented routes and will start working the day that permission
        is granted. Every probe is recorded and reported on failure, because this
        step is only diagnosable from the live response.
        """
        probes: list[str] = []

        # Granted directly as a business asset to the (system) user logging in.
        body = self._try(probes, "me/assigned_instagram_accounts", token, fields=self.IG_FIELDS)
        accounts = (body or {}).get("data") or []
        if accounts:
            return accounts[0]

        # Reached through a linked Facebook Page.
        body = self._try(
            probes, "me/accounts", token,
            fields=f"instagram_business_account{{{self.IG_FIELDS}}}",
        )
        for page in (body or {}).get("data") or []:
            account = page.get("instagram_business_account")
            if account:
                return account

        # Owned by, or shared with, a business the token can see.
        businesses = self._try(probes, "me/businesses", token, fields="id,name")
        for business in (businesses or {}).get("data") or []:
            account = self._business_account(probes, business["id"], token)
            if account:
                return account

        # The configured business, for when me/businesses is refused.
        if self.settings.ig_business_id:
            account = self._business_account(probes, self.settings.ig_business_id, token)
            if account:
                return account

        # Named outright, when nothing else can reach it.
        if self.settings.ig_user_id:
            account = self._try(probes, self.settings.ig_user_id, token, fields=self.IG_FIELDS)
            if account and account.get("id"):
                return account

        self._try(probes, "me", token, fields="id,name")
        raise InstagramError(
            "Could not find an Instagram account for this login. Probes: " + " | ".join(probes)
        )

    def subscribe_to_webhooks(self, token: str, ig_user_id: str) -> dict:
        """Ask Instagram to send this account's comment events to our webhook."""
        return self._request(
            "POST",
            f"{self.graph}/{ig_user_id}/subscribed_apps",
            params={"subscribed_fields": "comments", "access_token": token},
        )

    def list_media(self, token: str, ig_user_id: str, limit: int = 30) -> list[dict]:
        body = self._request(
            "GET",
            f"{self.graph}/{ig_user_id}/media",
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
