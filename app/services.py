import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .instagram import InstagramClient, InstagramError
from .matcher import find_matching_rule, render_message
from .models import Account, Activity, ProcessedComment, Rule, as_utc, utcnow
from .security import TokenCipher

log = logging.getLogger("reeldm")

PROCESSED_COMMENT_TTL = timedelta(days=8)  # private replies are only allowed for 7 days
ACTIVITY_RETENTION = timedelta(days=90)
REFRESH_WHEN_EXPIRING_WITHIN = timedelta(days=10)


@dataclass
class AppContext:
    settings: Settings
    sessions: sessionmaker[Session]
    ig: InstagramClient
    cipher: TokenCipher


def handle_comment(ctx: AppContext, ig_user_id: str, comment: dict) -> None:
    """Called for every "comments" webhook event. DMs the commenter if a rule matches."""
    comment_id = str(comment.get("id") or "")
    commenter = comment.get("from") or {}
    media_id = (comment.get("media") or {}).get("id")
    text = comment.get("text") or ""
    if not comment_id:
        return
    # Ignore the creator's own comments, including the public "check your DMs" replies we post
    if str(commenter.get("id")) == ig_user_id:
        return

    with ctx.sessions() as db:
        account = db.get(Account, ig_user_id)
        if account is None:
            return
        rules = db.scalars(select(Rule).where(Rule.ig_user_id == ig_user_id)).all()
        rule = find_matching_rule(rules, media_id, text)
        if rule is None:
            return

        # Meta can deliver the same event more than once; the primary key makes sure we DM once
        try:
            db.add(ProcessedComment(comment_id=comment_id, ig_user_id=ig_user_id))
            db.commit()
        except IntegrityError:
            db.rollback()
            return

        username = commenter.get("username")
        activity = Activity(
            ig_user_id=ig_user_id,
            rule_id=rule.id,
            rule_name=rule.name,
            comment_id=comment_id,
            media_id=media_id,
            username=username,
            comment_text=text[:2000],
        )
        try:
            token = ctx.cipher.decrypt(account.access_token_encrypted)
            ctx.ig.send_private_reply(token, ig_user_id, comment_id, render_message(rule.dm_message, username))
            activity.status = "sent"
            db.execute(update(Rule).where(Rule.id == rule.id).values(sent_count=Rule.sent_count + 1))
            if rule.public_reply:
                try:
                    ctx.ig.reply_to_comment(token, comment_id, render_message(rule.public_reply, username))
                except InstagramError as exc:
                    activity.error = f"DM sent, but the public reply failed: {exc}"
        except (InstagramError, ValueError) as exc:
            log.warning("DM for comment %s failed: %s", comment_id, exc)
            activity.status = "failed"
            activity.error = str(exc)
        db.add(activity)
        db.commit()


LONG_LIVED_TOKEN_SECONDS = 60 * 24 * 3600


def _long_lived_token(ctx: AppContext, token: str) -> dict:
    """Returns {"access_token", "expires_in"} for a token from Instagram login.

    Business Login for Instagram may already return a long-lived token. Instagram then
    rejects ig_exchange_token with code 100 "Unsupported request", so we keep the token we
    have. If it turns out to be short-lived, get_profile() right after fails or the user
    simply has to log in again; the daily refresh job extends it otherwise.
    """
    try:
        return ctx.ig.get_long_lived_token(token)
    except InstagramError as exc:
        if not exc.is_unsupported_request:
            raise
    try:
        # Confirms the token is long-lived and gives the real expiry (only works once it's 24h old)
        return ctx.ig.refresh_token(token)
    except InstagramError as exc:
        log.info("Login token is not refreshable yet (%s); using it as the long-lived token", exc)
    return {"access_token": token, "expires_in": LONG_LIVED_TOKEN_SECONDS}


def connect_account(ctx: AppContext, code: str) -> Account:
    """Finishes Instagram login: code -> long-lived token -> profile -> webhook subscription."""
    short = ctx.ig.exchange_code(code)
    t = str(short.get("access_token", ""))
    log.info(
        "Instagram login: user_id=%s permissions=%s token_prefix=%s token_len=%d",
        short.get("user_id"), short.get("permissions"), t[:4], len(t),
    )
    long = _long_lived_token(ctx, short["access_token"])
    token = long["access_token"]
    profile = ctx.ig.get_profile(token)
    ig_user_id = str(profile.get("user_id") or profile["id"])

    webhook_error = None
    try:
        ctx.ig.subscribe_to_webhooks(token)
    except InstagramError as exc:
        log.warning("Webhook subscription failed for %s: %s", profile.get("username"), exc)
        webhook_error = str(exc)

    with ctx.sessions() as db:
        account = db.get(Account, ig_user_id) or Account(ig_user_id=ig_user_id, connected_at=utcnow())
        account.app_scoped_id = str(profile.get("id") or "") or None
        account.username = profile.get("username") or ""
        account.name = profile.get("name")
        account.profile_picture_url = profile.get("profile_picture_url")
        account.account_type = profile.get("account_type")
        account.access_token_encrypted = ctx.cipher.encrypt(token)
        account.token_expires_at = utcnow() + timedelta(seconds=int(long.get("expires_in", 60 * 24 * 3600)))
        account.webhook_subscribed = webhook_error is None
        account.webhook_error = webhook_error
        db.add(account)
        db.commit()
        return account


def resubscribe_webhooks(ctx: AppContext, ig_user_id: str) -> Account:
    with ctx.sessions() as db:
        account = db.get(Account, ig_user_id)
        try:
            ctx.ig.subscribe_to_webhooks(ctx.cipher.decrypt(account.access_token_encrypted))
            account.webhook_subscribed, account.webhook_error = True, None
        except (InstagramError, ValueError) as exc:
            account.webhook_subscribed, account.webhook_error = False, str(exc)
        db.commit()
        return account


def delete_account_data(ctx: AppContext, user_id: str) -> bool:
    """Removes everything stored for an account (logout + delete, or Meta data-deletion request)."""
    with ctx.sessions() as db:
        accounts = db.scalars(
            select(Account).where(or_(Account.ig_user_id == user_id, Account.app_scoped_id == user_id))
        ).all()
        for account in accounts:
            db.execute(delete(ProcessedComment).where(ProcessedComment.ig_user_id == account.ig_user_id))
            db.execute(delete(Activity).where(Activity.ig_user_id == account.ig_user_id))
            db.execute(delete(Rule).where(Rule.ig_user_id == account.ig_user_id))
            db.delete(account)
        db.commit()
        return bool(accounts)


def account_stats(db: Session, ig_user_id: str) -> dict:
    week_ago = utcnow() - timedelta(days=7)
    total = db.scalar(select(func.coalesce(func.sum(Rule.sent_count), 0)).where(Rule.ig_user_id == ig_user_id))
    rows = db.execute(
        select(Activity.status, func.count())
        .where(Activity.ig_user_id == ig_user_id, Activity.created_at >= week_ago)
        .group_by(Activity.status)
    ).all()
    by_status = {status: count for status, count in rows}
    return {
        "total_sent": int(total or 0),
        "sent_7d": by_status.get("sent", 0),
        "failed_7d": by_status.get("failed", 0),
    }


def refresh_expiring_tokens(ctx: AppContext, now: datetime | None = None) -> int:
    """Long-lived tokens last 60 days; refresh any that expire within 10 days."""
    now = now or utcnow()
    refreshed = 0
    with ctx.sessions() as db:
        accounts = db.scalars(
            select(Account).where(Account.token_expires_at < now + REFRESH_WHEN_EXPIRING_WITHIN)
        ).all()
        for account in accounts:
            if as_utc(account.token_expires_at) <= now:
                continue  # already expired; the user has to log in again
            try:
                fresh = ctx.ig.refresh_token(ctx.cipher.decrypt(account.access_token_encrypted))
            except (InstagramError, ValueError) as exc:
                log.warning("Token refresh failed for @%s: %s", account.username, exc)
                continue
            account.access_token_encrypted = ctx.cipher.encrypt(fresh["access_token"])
            account.token_expires_at = now + timedelta(seconds=int(fresh.get("expires_in", 60 * 24 * 3600)))
            refreshed += 1
        db.commit()
    return refreshed


def cleanup_old_rows(ctx: AppContext, now: datetime | None = None) -> None:
    """Keeps the free-tier database small."""
    now = now or datetime.now(timezone.utc)
    with ctx.sessions() as db:
        db.execute(delete(ProcessedComment).where(ProcessedComment.created_at < now - PROCESSED_COMMENT_TTL))
        db.execute(delete(Activity).where(Activity.created_at < now - ACTIVITY_RETENTION))
        db.commit()
