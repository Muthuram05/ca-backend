"""Starts the real app with a fake Instagram, for the Playwright tests in ca-frontend/e2e.

    python tests/e2e_server.py   (serves on http://127.0.0.1:8765)

Never use this in production: anyone can "log in" here.
"""

import os
import sys
import tempfile
from pathlib import Path

import uvicorn
from cryptography.fernet import Fernet

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from fake_instagram import FakeInstagram  # noqa: E402

PORT = int(os.environ.get("E2E_PORT", "8765"))
BASE_URL = f"http://127.0.0.1:{PORT}"
WEBHOOK_SECRET = "e2e-app-secret"


def build_app():
    db_file = Path(tempfile.mkdtemp()) / "e2e.db"
    settings = Settings(
        base_url=BASE_URL,
        ig_app_id="e2e-app",
        ig_app_secret=WEBHOOK_SECRET,
        webhook_verify_token="e2e-verify",
        session_secret="e2e-session",
        token_encryption_key=Fernet.generate_key().decode(),
        database_url=os.environ.get("E2E_DATABASE_URL") or f"sqlite:///{db_file}",
        frontend_dist=Path(os.environ["FRONTEND_DIST"]) if os.environ.get("FRONTEND_DIST") else None,
    )
    fake = FakeInstagram(BASE_URL)
    app = create_app(settings, ig=fake, run_background_jobs=False)

    # Test-only peek at what would have been sent to Instagram
    @app.get("/__fake__/sent")
    def sent():
        return {"dms": fake.sent_dms, "public_replies": fake.public_replies}

    # Routes are matched in order; move ours ahead of the SPA catch-all
    app.router.routes.insert(0, app.router.routes.pop())
    return app


if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=PORT, log_level="warning")
