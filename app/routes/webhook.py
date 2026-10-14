import json

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import PlainTextResponse, Response

from ..deps import get_ctx
from ..security import verify_webhook_signature
from ..services import AppContext, handle_comment

router = APIRouter(prefix="/webhook")


@router.get("")
def verify(
    mode: str | None = Query(None, alias="hub.mode"),
    token: str | None = Query(None, alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
    ctx: AppContext = Depends(get_ctx),
):
    """Meta calls this once when you save the webhook URL in the App Dashboard."""
    if mode == "subscribe" and token == ctx.settings.webhook_verify_token:
        return PlainTextResponse(challenge)
    return Response(status_code=403)


@router.post("")
async def receive(request: Request, background: BackgroundTasks, ctx: AppContext = Depends(get_ctx)):
    body = await request.body()
    if not verify_webhook_signature(ctx.settings.ig_app_secret, body, request.headers.get("x-hub-signature-256")):
        return Response(status_code=401)
    try:
        payload = json.loads(body)
    except ValueError:
        return Response(status_code=400)

    if payload.get("object") == "instagram":
        for entry in payload.get("entry") or []:
            for change in entry.get("changes") or []:
                if change.get("field") == "comments" and isinstance(change.get("value"), dict):
                    # Runs after the response is sent; Meta retries if we answer slowly
                    background.add_task(handle_comment, ctx, str(entry.get("id")), change["value"])
    return Response(status_code=200)
