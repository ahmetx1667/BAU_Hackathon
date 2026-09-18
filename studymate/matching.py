"""Match scoring: how well a student fits a study session.

Two implementations behind one call. `match_score` asks an LLM when an API key is
configured; otherwise — and whenever the call fails — it falls back to keyword
overlap. The fallback is not a stub: it is what runs on a fresh clone, and it is
what kept the demo alive when the network did not.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.request

from .config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_TIMEOUT_SECONDS,
    DEEPSEEK_URL,
)
from .formatting import display_label, slug_words

# Scores are stable for a (student, post) pair, and a posts page renders many
# cards at once — without this the page would make one API call per card.
_match_cache: dict[tuple[int, int], tuple[int, str]] = {}


def clear_cache_for_user(user_id: int) -> None:
    """Drop a student's cached scores after they edit their profile."""
    for key in [k for k in _match_cache if k[0] == user_id]:
        del _match_cache[key]


def _post_skills(post: sqlite3.Row) -> str:
    """The post author's interests, when the query joined them in."""
    try:
        return post["skills"] or ""
    except (IndexError, KeyError):
        return ""


def match_score_basic(user: sqlite3.Row, post: sqlite3.Row) -> tuple[int, str]:
    """Keyword-overlap scoring — the offline fallback.

    Starts at 45 so an unrelated post still reads as "possible" rather than a
    hard no, and caps at 96 so nothing ever claims certainty.
    """
    user_words = slug_words(f'{user["skills"]} {user["bio"]}')
    post_words = slug_words(f'{post["topic"]} {post["description"]} {_post_skills(post)}')
    overlap = user_words & post_words

    score = min(96, 45 + len(overlap) * 12)
    if overlap:
        reason = "Shared keywords: " + ", ".join(sorted(overlap)[:4])
    else:
        reason = "Basic fit, based on topic and timing."
    return score, reason


def _build_prompt(user: sqlite3.Row, post: sqlite3.Row) -> str:
    user_info = (
        f"Name: {user['name']}, University: {user['school']}, "
        f"Interests: {user['skills']}, Bio: {user['bio']}"
    )
    post_info = (
        f"Topic: {post['topic']}, Level: {display_label(post['level'])}, "
        f"Description: {post['description']}, Author's interests: {_post_skills(post)}"
    )
    return (
        f"Student: {user_info}\n"
        f"Session: {post_info}\n\n"
        "Reply in exactly this format:\n"
        "SCORE: [a number from 0 to 100]\n"
        "REASON: [one short sentence]"
    )


def _parse_response(content: str) -> tuple[int, str]:
    score = 50
    reason = "Assessed by the matching model."
    for line in content.split("\n"):
        line = line.strip()
        if line.upper().startswith("SCORE:"):
            try:
                raw = line.split(":", 1)[1].strip().replace("%", "")
                score = max(0, min(100, int(raw)))
            except (ValueError, IndexError):
                pass  # keep the default rather than fail the page
        elif line.upper().startswith("REASON:"):
            reason = line.split(":", 1)[1].strip()
    return score, reason


def match_score(user: sqlite3.Row, post: sqlite3.Row) -> tuple[int, str]:
    """Score a post for a student, and explain the score in one sentence."""
    if not DEEPSEEK_API_KEY:
        return match_score_basic(user, post)

    cache_key = (user["id"], post["id"])
    if cache_key in _match_cache:
        return _match_cache[cache_key]

    # Nothing to reason about, and no point spending a call on it.
    if not user["skills"].strip() and not user["bio"].strip():
        result = (50, "Add your interests and bio to get a real match score.")
        _match_cache[cache_key] = result
        return result

    try:
        payload = json.dumps(
            {
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "You score how well a student matches a study session. Answer briefly."},
                    {"role": "user", "content": _build_prompt(user, post)},
                ],
                "max_tokens": 60,
                "temperature": 0.3,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            DEEPSEEK_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            },
        )
        with urllib.request.urlopen(request, timeout=DEEPSEEK_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))

        result = _parse_response(body["choices"][0]["message"]["content"].strip())
        _match_cache[cache_key] = result
        return result

    except Exception as exc:
        # A scoring API being down must never take the page down with it.
        print(f"[match] DeepSeek request failed, using keyword scoring: {exc}")
        result = match_score_basic(user, post)
        _match_cache[cache_key] = result
        return result
