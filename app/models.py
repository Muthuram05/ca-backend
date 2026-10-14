import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; Postgres keeps it. Treat naive values as UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    # Professional account ID; matches entry.id in webhooks
    ig_user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # App-scoped ID from /me "id"; Meta's deauthorize / data-deletion callbacks may use it
    app_scoped_id: Mapped[str | None] = mapped_column(String(64), index=True)
    username: Mapped[str] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(255))
    profile_picture_url: Mapped[str | None] = mapped_column(Text)
    account_type: Mapped[str | None] = mapped_column(String(32))
    access_token_encrypted: Mapped[str] = mapped_column(Text)
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    webhook_subscribed: Mapped[bool] = mapped_column(Boolean, default=False)
    webhook_error: Mapped[str | None] = mapped_column(Text)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ig_user_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.ig_user_id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    # None means "all reels and posts"
    media_id: Mapped[str | None] = mapped_column(String(64))
    media_label: Mapped[str | None] = mapped_column(String(160))
    media_thumbnail_url: Mapped[str | None] = mapped_column(Text)
    match_type: Mapped[str] = mapped_column(String(16), default="contains")
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    dm_message: Mapped[str] = mapped_column(Text)
    public_reply: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProcessedComment(Base):
    """One row per comment we've acted on. The primary key makes "DM each comment once" atomic."""

    __tablename__ = "processed_comments"

    comment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ig_user_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Activity(Base):
    __tablename__ = "activity"
    __table_args__ = (Index("ix_activity_account_created", "ig_user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ig_user_id: Mapped[str] = mapped_column(ForeignKey("accounts.ig_user_id", ondelete="CASCADE"))
    rule_id: Mapped[str | None] = mapped_column(String(36))
    rule_name: Mapped[str | None] = mapped_column(String(80))
    comment_id: Mapped[str] = mapped_column(String(64))
    media_id: Mapped[str | None] = mapped_column(String(64))
    username: Mapped[str | None] = mapped_column(String(64))
    comment_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))  # "sent" | "failed"
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
