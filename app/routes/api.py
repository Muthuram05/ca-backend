from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import current_account, get_ctx, get_db
from ..instagram import InstagramError
from ..matcher import parse_keywords, preview
from ..models import Account, Activity, Rule, as_utc
from ..services import AppContext, account_stats, delete_account_data, resubscribe_webhooks

router = APIRouter(prefix="/api")


# ---------- Schemas ----------


class RuleIn(BaseModel):
    name: str = Field("", max_length=80)
    media_id: str | None = Field(None, max_length=64)
    media_label: str | None = Field(None, max_length=160)
    media_thumbnail_url: str | None = Field(None, max_length=2000)
    match_type: Literal["contains", "exact", "any"] = "contains"
    keywords: list[str] | str = []
    dm_message: str = Field(..., max_length=1000)
    public_reply: str | None = Field(None, max_length=300)
    enabled: bool = True

    @field_validator("keywords", mode="after")
    @classmethod
    def _keywords(cls, value):
        return parse_keywords(value)

    @field_validator("name", "dm_message", "public_reply", "media_id", mode="after")
    @classmethod
    def _strip(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _check(self):
        if self.match_type != "any" and not self.keywords:
            raise ValueError("Add at least one keyword")
        if not self.dm_message:
            raise ValueError("The DM message can't be empty")
        self.media_id = self.media_id or None
        self.public_reply = self.public_reply or None
        self.name = self.name or (", ".join(self.keywords) if self.keywords else "Any comment")[:80]
        return self


class RuleOut(BaseModel):
    id: str
    name: str
    media_id: str | None
    media_label: str | None
    media_thumbnail_url: str | None
    match_type: str
    keywords: list[str]
    dm_message: str
    public_reply: str | None
    enabled: bool
    sent_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class EnabledIn(BaseModel):
    enabled: bool


class TestCommentIn(BaseModel):
    text: str = Field(..., max_length=2200)
    media_id: str | None = None
    username: str | None = Field("your_follower", max_length=64)


class ActivityOut(BaseModel):
    id: int
    rule_id: str | None
    rule_name: str | None
    comment_id: str
    media_id: str | None
    username: str | None
    comment_text: str | None
    status: str
    error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------- Account ----------


def _me(db: Session, account: Account) -> dict:
    return {
        "ig_user_id": account.ig_user_id,
        "username": account.username,
        "name": account.name,
        "profile_picture_url": account.profile_picture_url,
        "token_expires_at": as_utc(account.token_expires_at),
        "webhook_subscribed": account.webhook_subscribed,
        "webhook_error": account.webhook_error,
        "stats": account_stats(db, account.ig_user_id),
    }


@router.get("/me")
def me(db: Session = Depends(get_db), account: Account = Depends(current_account)):
    return _me(db, account)


@router.post("/account/resubscribe")
def resubscribe(
    db: Session = Depends(get_db),
    account: Account = Depends(current_account),
    ctx: AppContext = Depends(get_ctx),
):
    resubscribe_webhooks(ctx, account.ig_user_id)
    db.refresh(account)
    return _me(db, account)


@router.delete("/account", status_code=204)
def delete_account(request: Request, account: Account = Depends(current_account), ctx: AppContext = Depends(get_ctx)):
    delete_account_data(ctx, account.ig_user_id)
    request.session.clear()
    return Response(status_code=204)


@router.get("/media")
def media(account: Account = Depends(current_account), ctx: AppContext = Depends(get_ctx)):
    try:
        return ctx.ig.list_media(ctx.cipher.decrypt(account.access_token_encrypted))
    except (InstagramError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Could not load your reels: {exc}") from exc


# ---------- Rules ----------


def _rules(db: Session, ig_user_id: str) -> list[Rule]:
    return list(db.scalars(select(Rule).where(Rule.ig_user_id == ig_user_id).order_by(Rule.created_at)))


def _get_rule(db: Session, account: Account, rule_id: str) -> Rule:
    rule = db.get(Rule, rule_id)
    if rule is None or rule.ig_user_id != account.ig_user_id:
        raise HTTPException(status_code=404, detail="Automation not found")
    return rule


@router.get("/rules", response_model=list[RuleOut])
def list_rules(db: Session = Depends(get_db), account: Account = Depends(current_account)):
    return _rules(db, account.ig_user_id)


@router.post("/rules", response_model=RuleOut, status_code=201)
def create_rule(body: RuleIn, db: Session = Depends(get_db), account: Account = Depends(current_account)):
    rule = Rule(ig_user_id=account.ig_user_id, **body.model_dump())
    db.add(rule)
    db.commit()
    return rule


@router.put("/rules/{rule_id}", response_model=RuleOut)
def update_rule(
    rule_id: str, body: RuleIn, db: Session = Depends(get_db), account: Account = Depends(current_account)
):
    rule = _get_rule(db, account, rule_id)
    for key, value in body.model_dump().items():
        setattr(rule, key, value)
    db.commit()
    return rule


@router.patch("/rules/{rule_id}", response_model=RuleOut)
def toggle_rule(
    rule_id: str, body: EnabledIn, db: Session = Depends(get_db), account: Account = Depends(current_account)
):
    rule = _get_rule(db, account, rule_id)
    rule.enabled = body.enabled
    db.commit()
    return rule


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: str, db: Session = Depends(get_db), account: Account = Depends(current_account)):
    db.delete(_get_rule(db, account, rule_id))
    db.commit()
    return Response(status_code=204)


@router.post("/rules/test")
def test_comment(body: TestCommentIn, db: Session = Depends(get_db), account: Account = Depends(current_account)):
    """Dry run: which automation would answer this comment, and with what DM. Sends nothing."""
    result = preview(_rules(db, account.ig_user_id), body.media_id, body.text, body.username)
    return {
        "matched": result.rule is not None,
        "rule": RuleOut.model_validate(result.rule) if result.rule else None,
        "dm": result.dm,
        "public_reply": result.public_reply,
    }


# ---------- Activity ----------


@router.get("/activity", response_model=list[ActivityOut])
def activity(limit: int = 50, db: Session = Depends(get_db), account: Account = Depends(current_account)):
    limit = max(1, min(limit, 200))
    return list(
        db.scalars(
            select(Activity)
            .where(Activity.ig_user_id == account.ig_user_id)
            .order_by(Activity.created_at.desc(), Activity.id.desc())
            .limit(limit)
        )
    )
