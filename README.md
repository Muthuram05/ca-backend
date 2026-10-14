# ca-backend: Reel DM Automation API

Python (FastAPI) backend for **Reel DM Automation**: when someone comments a keyword (like `link`)
on an Instagram reel, they automatically get a DM.
The React dashboard lives in [ca-frontend](https://github.com/admin-stilltyping/ca-frontend).

What this service does:

- **Instagram login** (OAuth). Long-lived tokens are encrypted in the database and refreshed automatically.
- **Automations API**: create, update, pause and delete automations, plus a dry-run "test a comment" endpoint.
- **Webhook** `/webhook`: verifies Meta's signature, then sends a DM to each matching comment **exactly
  once** using Instagram's Private Replies API, with an optional public reply.
- **Meta App Review callbacks**: data deletion and deauthorize.
- **Maintenance**: token refresh and cleanup of old rows (keeps the free database small).

```
Follower comments "link pls"  →  Instagram  →  POST /webhook (signed)
   → match automation → claim comment in DB (DM once) → POST /{ig-user-id}/messages → activity log
```

## Stack

FastAPI · SQLAlchemy 2 · PostgreSQL (Supabase free tier) via psycopg 3 · httpx · pytest

**Why Supabase Postgres:** it's free (500 MB, no card) and it's plain PostgreSQL, so there's no lock-in.
A unique key guarantees each comment is DMed once. Supabase pauses free projects after 7 days with no
activity; webhook traffic and an uptime ping on `/healthz`, which runs a database query, keep it awake.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                 # fill in, see table below
python -m app                        # http://localhost:8000  (API docs: /api/docs)
```

Then run [ca-frontend](https://github.com/admin-stilltyping/ca-frontend) (`npm run dev`, port 5173)
and `ngrok http 5173`. Put the ngrok **https** URL in `BASE_URL` and open that URL in the browser.

| Variable | Value |
| --- | --- |
| `BASE_URL` | Public URL of the **frontend** (ngrok URL locally, Netlify URL in production) |
| `IG_APP_ID`, `IG_APP_SECRET` | Meta app → Instagram → API setup with Instagram login |
| `WEBHOOK_VERIFY_TOKEN` | Any random string; enter the same in Meta's webhook settings |
| `SESSION_SECRET` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `TOKEN_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` (keep it safe) |
| `DATABASE_URL` | Supabase → **Connect** → **Transaction pooler** URI (port 6543) + `?sslmode=require` |
| `FRONTEND_DIST` | Optional: path to a built ca-frontend, to serve both from this one app |

## Deploy free on Render

1. Create a free Supabase project and copy its Transaction pooler URI.
2. On Render: **New → Blueprint →** this repo. [`render.yaml`](render.yaml) creates a free Docker web
   service. Fill in the env vars, with `BASE_URL` = your Netlify frontend URL.
3. Add a free [UptimeRobot](https://uptimerobot.com) monitor on `https://YOUR-BACKEND.onrender.com/healthz`
   every 5 minutes. This stops Render's free instance from sleeping, which would delay DMs.

## Meta app settings

| Setting | Value |
| --- | --- |
| OAuth redirect URI | `https://FRONTEND_URL/auth/instagram/callback` |
| Webhook callback URL | `https://BACKEND_URL/webhook` (subscribe to the **comments** field) |
| Webhook verify token | `WEBHOOK_VERIFY_TOKEN` |
| Privacy policy URL | `https://FRONTEND_URL/privacy` |
| Data deletion callback | `https://FRONTEND_URL/auth/instagram/data-deletion` |
| Deauthorize callback | `https://FRONTEND_URL/auth/instagram/deauthorize` |

Permissions: `instagram_business_basic`, `instagram_business_manage_comments`,
`instagram_business_manage_messages`. Until **App Review** approves them, only accounts added as
Instagram Testers can log in. Users need a Business or Creator account.

## Tests

```bash
pytest                                                                                 # SQLite
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/reeldm_test pytest     # real Postgres
```

64 tests cover login, the API, webhook-to-DM, de-duplication, matching (including Tamil and Hindi keywords),
encryption, signatures, maintenance jobs and static serving. CI runs both databases on every push.
`tests/e2e_server.py` runs the app with a fake Instagram for ca-frontend's Playwright tests.

## Layout

```
app/
  main.py        app factory, /healthz, optional static frontend
  config.py      settings from env
  models.py      accounts, rules, processed_comments, activity
  instagram.py   Instagram Graph API client
  services.py    comment → DM, login, token refresh, cleanup
  matcher.py     keyword matching
  security.py    token encryption, webhook signatures, signed_request
  routes/        auth.py, api.py, webhook.py
tests/           pytest suite, fake Instagram, E2E server
```
