from dataclasses import dataclass, field

from app.matcher import find_matching_rule, normalize, parse_keywords, preview, render_message, rule_matches_text


@dataclass
class R:
    keywords: list[str] = field(default_factory=lambda: ["link"])
    match_type: str = "contains"
    media_id: str | None = None
    enabled: bool = True
    created_at: str = "2026-01-01"
    id: str = "r"
    dm_message: str = "Hi {username}"
    public_reply: str | None = None


def test_normalize_strips_case_punctuation_and_emoji():
    assert normalize("  LINK!!! 🙏  please ") == "link please"
    assert normalize(None) == ""


def test_parse_keywords_from_string_and_list():
    assert parse_keywords(" Link, LINK!,  send me ,, ") == ["link", "send me"]
    assert parse_keywords(["Guide", "guide", ""]) == ["guide"]
    assert parse_keywords(None) == []


def test_contains_matches_whole_words_only():
    rule = R()
    assert rule_matches_text(rule, "LINK")
    assert rule_matches_text(rule, "link please 🙏")
    assert rule_matches_text(rule, "can I get the link?")
    assert not rule_matches_text(rule, "linkedin")
    assert not rule_matches_text(rule, "nice video")
    assert not rule_matches_text(rule, "")


def test_contains_multi_word_keyword():
    rule = R(keywords=["send me"])
    assert rule_matches_text(rule, "pls SEND ME the guide")
    assert not rule_matches_text(rule, "send it to me")


def test_exact_requires_whole_comment():
    rule = R(match_type="exact")
    assert rule_matches_text(rule, " Link! ")
    assert not rule_matches_text(rule, "link please")


def test_any_matches_everything():
    assert rule_matches_text(R(match_type="any", keywords=[]), "wow")


def test_non_latin_keywords():
    rule = R(keywords=parse_keywords("லிங்க், लिंक"))
    assert rule_matches_text(rule, "லிங்க் please")
    assert rule_matches_text(rule, "लिंक!!")
    assert not rule_matches_text(rule, "லிங்")


def test_specific_reel_rule_beats_global_and_disabled_rules_are_skipped():
    global_rule = R(id="global")
    specific = R(id="specific", media_id="reel1", created_at="2026-02-01")
    paused = R(id="paused", media_id="reel2", enabled=False)
    rules = [global_rule, specific, paused]
    assert find_matching_rule(rules, "reel1", "link").id == "specific"
    assert find_matching_rule(rules, "reel2", "link").id == "global"
    assert find_matching_rule(rules, "reel1", "hello") is None


def test_oldest_rule_wins_a_tie():
    rules = [R(id="new", created_at="2026-03-01"), R(id="old", created_at="2026-01-01")]
    assert find_matching_rule(rules, None, "link").id == "old"


def test_render_message():
    assert render_message("Hi {username}, here you go", "sam") == "Hi @sam, here you go"
    assert render_message("Hi {username}!", None) == "Hi there!"


def test_preview():
    result = preview([R(public_reply="Sent {username}!")], None, "link", "sam")
    assert (result.dm, result.public_reply) == ("Hi @sam", "Sent @sam!")
    assert preview([R()], None, "nope", "sam").rule is None
