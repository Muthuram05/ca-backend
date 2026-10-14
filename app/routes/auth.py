import logging
import secrets
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from ..deps import get_ctx
from ..instagram import InstagramError
from ..security import parse_signed_request
from ..services import AppContext, connect_account, delete_account_data

log = logging.getLogger("reeldm")
router = APIRouter(prefix="/auth")


def _home(**params: str) -> RedirectResponse:
    query = "&".join(f"{k}={quote(v)}" for k, v in params.items())
    return RedirectResponse(f"/?{query}" if query else "/", status_code=303)


@router.get("/instagram")
def login(request: Request, ctx: AppContext = Depends(get_ctx)):
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    return RedirectResponse(ctx.ig.authorize_url(state), status_code=303)


@router.get("/instagram/callback")
def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error_description: str | None = None,
    ctx: AppContext = Depends(get_ctx),
):
    if error_description:
        return _home(error=f"Instagram login was cancelled: {error_description}")
    expected_state = request.session.pop("oauth_state", None)
    if not code or not state or not expected_state or not secrets.compare_digest(state, expected_state):
        return _home(error="Login expired, please try again.")

    try:
        # Instagram appends "#_" to the code
        account = connect_account(ctx, code.removesuffix("#_"))
    except (InstagramError, KeyError) as exc:
        log.warning("Instagram login failed: %s", exc)
        return _home(error=f"Instagram login failed: {exc}")

    request.session.clear()
    request.session["ig_user_id"] = account.ig_user_id
    if not account.webhook_subscribed:
        return _home(warning=f"Logged in, but comment events could not be enabled: {account.webhook_error}")
    return _home()


@router.post("/logout", status_code=204)
def logout(request: Request):
    request.session.clear()
    return Response(status_code=204)


# ---------- Callbacks Meta requires for App Review ----------


def _user_from_signed_request(ctx: AppContext, signed_request: str) -> str:
    data = parse_signed_request(ctx.settings.ig_app_secret, signed_request)
    if not data or not data.get("user_id"):
        raise HTTPException(status_code=400, detail="Invalid signed_request")
    return str(data["user_id"])


@router.post("/instagram/deauthorize")
def deauthorize(signed_request: str = Form(...), ctx: AppContext = Depends(get_ctx)):
    """Meta calls this when a user removes the app from their Instagram settings."""
    delete_account_data(ctx, _user_from_signed_request(ctx, signed_request))
    return {"success": True}


@router.post("/instagram/data-deletion")
def data_deletion(signed_request: str = Form(...), ctx: AppContext = Depends(get_ctx)):
    """Meta calls this when a user asks for their data to be deleted."""
    user_id = _user_from_signed_request(ctx, signed_request)
    delete_account_data(ctx, user_id)
    code = secrets.token_hex(8)
    return {"url": f"{ctx.settings.base_url}/deletion?code={code}", "confirmation_code": code}
