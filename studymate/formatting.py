"""Escaping, display labels, date formatting and input normalisation.

Everything user-supplied passes through `escape()` before it reaches a template.
The templates are plain f-strings, so this is the only thing standing between a
posted description and stored XSS — there is no autoescaping to fall back on.
"""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from typing import Any

from .constants import (
    LABELS,
    LEVELS,
    LOCATIONS,
    MODES,
    PLACES,
    SCHOOL_LABEL_REPLACEMENTS,
    STATUS_LABELS,
    STOP_WORDS,
)
from .errors import ValidationError

# ---- Clocks ----------------------------------------------------------------
#
# Two clocks on purpose. Stored timestamps (sessions, created_at) are UTC, so
# they are unambiguous. Study times are local wall-clock, because "18:00" on a
# study post means six in the evening where the students actually are.


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def localnow() -> datetime:
    return datetime.now().replace(second=0, microsecond=0)


def now_iso() -> str:
    return utcnow().isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def datetime_local(value: str | None = None) -> str:
    """A value for an <input type="datetime-local">, defaulting to an hour from now."""
    if value:
        return value[:16]
    return (localnow() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")


def current_datetime_local() -> str:
    return localnow().strftime("%Y-%m-%dT%H:%M")


# ---- Display ---------------------------------------------------------------


def escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def display_label(value: str) -> str:
    return LABELS.get(value, value)


def status_label(value: str) -> str:
    return STATUS_LABELS.get(value, value)


def display_school(name: str) -> str:
    """Restore Turkish spelling in a university name for display."""
    label = name
    for old, new in SCHOOL_LABEL_REPLACEMENTS.items():
        label = label.replace(old, new)
    return label


def meta_spans(values: list[str]) -> str:
    """Render a card's metadata row, skipping blanks and duplicates.

    Online posts set location, mode and place all to "Online", so without the
    de-duplication the row would read "Online Online Online".
    """
    seen: set[str] = set()
    spans = []
    for value in values:
        label = display_label(value)
        if not label or label in seen:
            continue
        seen.add(label)
        spans.append(f"<span>{escape(label)}</span>")
    return "".join(spans)


def display_date_label(parsed: datetime) -> str:
    today = localnow().date()
    if parsed.date() == today:
        return "Today"
    if parsed.date() == today + timedelta(days=1):
        return "Tomorrow"
    if parsed.date() == today - timedelta(days=1):
        return "Yesterday"
    return parsed.strftime("%d.%m.%Y")


def display_datetime(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value.replace("T", " ")
    return f"{display_date_label(parsed)} {parsed:%H:%M}"


def display_time_range(start: str, end: str) -> str:
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError:
        return f"{display_datetime(start)} - {display_datetime(end)}"
    if start_dt.date() == end_dt.date():
        return f"{display_date_label(start_dt)} {start_dt:%H:%M} - {end_dt:%H:%M}"
    return f"{display_datetime(start)} - {display_datetime(end)}"


# ---- Keyword extraction ----------------------------------------------------


def slug_words(text: str) -> set[str]:
    """Reduce free text to a set of content words for keyword match scoring.

    Non-alphanumerics become separators, anything three characters or shorter is
    dropped, and stop words are removed — see STOP_WORDS for why both languages
    are filtered.
    """
    cleaned = []
    for ch in text.lower():
        cleaned.append(ch if ch.isalnum() else " ")
    words = {w for w in "".join(cleaned).split() if len(w) > 2}
    return words - STOP_WORDS


# ---- Input normalisation ---------------------------------------------------


def normalize_phone(value: str, redirect_to: str, required: bool = False) -> str:
    value = " ".join(value.strip().split())[:32]
    if required and not value:
        raise ValidationError("A phone number is required.", redirect_to)
    allowed = set("+0123456789 ()-")
    if value and (any(ch not in allowed for ch in value) or sum(ch.isdigit() for ch in value) < 10):
        raise ValidationError(
            "A phone number needs at least 10 digits and may only contain +, spaces, hyphens and brackets.",
            redirect_to,
        )
    return value


def validate_study_times(start_time: str, end_time: str) -> None:
    try:
        start = datetime.fromisoformat(start_time)
        end = datetime.fromisoformat(end_time)
    except ValueError:
        raise ValidationError("Enter a valid start and end time.", "/posts/new")
    if start >= end:
        raise ValidationError("The end time has to come after the start time.", "/posts/new")
    if end <= localnow():
        raise ValidationError("That session has already ended.", "/posts/new")
    # Five minutes of slack, so a post is not rejected for the time it took to fill in the form.
    if start < localnow() - timedelta(minutes=5):
        raise ValidationError("You cannot post a session that started in the past.", "/posts/new")


def normalize_study_context(
    location: str, mode: str, place: str, redirect_to: str
) -> tuple[str, str, str]:
    """Keep location, mode and place consistent with one another.

    An online session has no district and no venue, so all three collapse to
    "Online". An in-person one must have both.
    """
    if location not in LOCATIONS or mode not in MODES or place not in PLACES:
        raise ValidationError("Check the session details.", redirect_to)
    if mode == "Online":
        return "Online", mode, "Online"
    if location == "Online" or place == "Online":
        raise ValidationError("An in-person session needs a district and a venue.", redirect_to)
    return location, mode, place


def validate_level(level: str, redirect_to: str) -> str:
    if level not in LEVELS:
        raise ValidationError("Choose a valid level.", redirect_to)
    return level
