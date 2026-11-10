import os
from dataclasses import dataclass
from pathlib import Path


# The Facebook Login for Business configuration this app logs in through.
# Not a secret: it travels in the query string of every login URL. Override
# with IG_CONFIG_ID when pointing the backend at a different Meta app.
DEFAULT_IG_CONFIG_ID = "28213409225000127"


class ConfigError(RuntimeError):
    pass


def normalize_database_url(url: str) -> str:
    """Accept the plain postgres:// URLs Supabase/Neon show and pick the psycopg 3 driver."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@dataclass(frozen=True)
class Settings:
    # Public HTTPS URL users and Instagram reach this app on, e.g. https://reeldm.onrender.com
    base_url: str
    # Meta App Dashboard > Instagram > API setup with Instagram login
    ig_app_id: str
    ig_app_secret: str
    # Facebook Login for Business configuration; replaces the scope list.
    # from_env() falls back to DEFAULT_IG_CONFIG_ID when the variable is unset.
    ig_config_id: str
    # Any random string; the same value goes into the webhook config in the Meta dashboard
    webhook_verify_token: str
    # Signs the login cookie
    session_secret: str
    # Fernet key used to encrypt Instagram access tokens at rest
    token_encryption_key: str
    database_url: str
    # Optional. The login only grants Instagram permissions, never business_management,
    # so me/businesses is refused and the owning portfolio cannot be discovered from the
    # token. Naming it here lets the account be found through the business instead.
    ig_business_id: str = ""
    # Optional last resort: the Instagram user id to use when no probe finds one.
    ig_user_id: str = ""
    graph_version: str = "v23.0"
    # Optional: folder with a built ca-frontend (npm run build) to serve from this same app
    frontend_dist: Path | None = None

    @property
    def redirect_uri(self) -> str:
        return f"{self.base_url}/auth/instagram/callback"

    @property
    def cookie_secure(self) -> bool:
        return self.base_url.startswith("https://")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        names = [
            "BASE_URL",
            "IG_APP_ID",
            "IG_APP_SECRET",
            "WEBHOOK_VERIFY_TOKEN",
            "SESSION_SECRET",
            "TOKEN_ENCRYPTION_KEY",
            "DATABASE_URL",
        ]
        missing = [n for n in names if not env.get(n)]
        if missing:
            raise ConfigError(f"Missing environment variables: {', '.join(missing)}. See .env.example.")
        return cls(
            base_url=env["BASE_URL"].rstrip("/"),
            ig_app_id=env["IG_APP_ID"],
            ig_app_secret=env["IG_APP_SECRET"],
            ig_config_id=env.get("IG_CONFIG_ID") or DEFAULT_IG_CONFIG_ID,
            webhook_verify_token=env["WEBHOOK_VERIFY_TOKEN"],
            session_secret=env["SESSION_SECRET"],
            token_encryption_key=env["TOKEN_ENCRYPTION_KEY"],
            database_url=normalize_database_url(env["DATABASE_URL"]),
            ig_business_id=env.get("IG_BUSINESS_ID") or "",
            ig_user_id=env.get("IG_USER_ID") or "",
            graph_version=env.get("IG_GRAPH_VERSION") or "v23.0",
            frontend_dist=Path(env["FRONTEND_DIST"]) if env.get("FRONTEND_DIST") else None,
        )
