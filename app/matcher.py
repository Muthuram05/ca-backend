"""Pure keyword-matching logic, kept free of I/O so it is easy to test."""

import unicodedata
from dataclasses import dataclass
from typing import Iterable, Protocol


class RuleLike(Protocol):
    enabled: bool
    media_id: str | None
    match_type: str
    keywords: list[str]
    created_at: object


def normalize(text: str | None) -> str:
    """Lowercase, drop punctuation/emoji, collapse spaces.

    Letters and combining marks are kept so keywords in Tamil, Hindi etc. work.
    """
    text = unicodedata.normalize("NFKC", text or "").casefold()
    chars = [c if unicodedata.category(c)[0] in "LMN" else " " for c in text]
    return " ".join("".join(chars).split())


def parse_keywords(value: str | Iterable[str] | None) -> list[str]:
    items = value.split(",") if isinstance(value, str) else list(value or [])
    seen: dict[str, None] = {}
    for item in items:
        kw = normalize(item)
        if kw:
            seen.setdefault(kw, None)
    return list(seen)


def rule_matches_text(rule: RuleLike, comment_text: str | None) -> bool:
    if rule.match_type == "any":
        return True
    text = normalize(comment_text)
    if not text:
        return False
    if rule.match_type == "exact":
        return text in rule.keywords
    # "contains": whole words only, so "link" matches "LINK pls!" but not "linkedin"
    padded = f" {text} "
    return any(f" {kw} " in padded for kw in rule.keywords)


def find_matching_rule(rules: Iterable[RuleLike], media_id: str | None, text: str | None):
    """Rules pinned to this reel beat "all reels" rules; ties go to the oldest rule."""
    candidates = [
        r
        for r in rules
        if r.enabled and (r.media_id is None or r.media_id == media_id) and rule_matches_text(r, text)
    ]
    candidates.sort(key=lambda r: (r.media_id is None, str(r.created_at)))
    return candidates[0] if candidates else None


def render_message(template: str, username: str | None) -> str:
    return template.replace("{username}", f"@{username}" if username else "there")


@dataclass
class MatchPreview:
    rule: object | None
    dm: str | None
    public_reply: str | None


def preview(rules: Iterable[RuleLike], media_id: str | None, text: str, username: str | None) -> MatchPreview:
    rule = find_matching_rule(rules, media_id, text)
    if rule is None:
        return MatchPreview(None, None, None)
    reply = render_message(rule.public_reply, username) if getattr(rule, "public_reply", None) else None
    return MatchPreview(rule, render_message(rule.dm_message, username), reply)
