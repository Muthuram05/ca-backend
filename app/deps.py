from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .models import Account
from .services import AppContext


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def get_db(ctx: AppContext = Depends(get_ctx)) -> Iterator[Session]:
    with ctx.sessions() as db:
        yield db


def current_account(request: Request, db: Session = Depends(get_db)) -> Account:
    ig_user_id = request.session.get("ig_user_id")
    account = db.get(Account, ig_user_id) if ig_user_id else None
    if account is None:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not logged in")
    return account
