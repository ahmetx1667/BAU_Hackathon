"""The Turkish university list, and the .edu address rule built on top of it.

Registration never takes a free-text email. The student picks their university
and types only the local part; the domain comes from the dataset. That means an
account can only exist for a real Turkish university address, which is the whole
basis for trusting that the other person is a student.
"""

from __future__ import annotations

import json

from .config import EMAIL_LOCAL_RE, UNIVERSITIES_PATH
from .errors import ValidationError
from .formatting import display_school, escape


def load_universities() -> list[dict[str, str]]:
    if not UNIVERSITIES_PATH.exists():
        return []
    rows = json.loads(UNIVERSITIES_PATH.read_text(encoding="utf-8"))
    return [
        {"name": str(row["name"]), "domain": str(row["domain"]).lower()}
        for row in rows
        if row.get("name") and row.get("domain")
    ]


UNIVERSITIES = load_universities()
UNIVERSITY_BY_NAME = {row["name"]: row for row in UNIVERSITIES}


def default_school() -> str:
    """The university pre-selected on the signup form."""
    if "Bahcesehir University" in UNIVERSITY_BY_NAME:
        return "Bahcesehir University"
    return UNIVERSITIES[0]["name"] if UNIVERSITIES else ""


def default_domain() -> str:
    return UNIVERSITY_BY_NAME.get(default_school(), {}).get("domain", "edu.tr")


def require_university(name: str, redirect_to: str) -> dict[str, str]:
    university = UNIVERSITY_BY_NAME.get(name)
    if not university:
        raise ValidationError("Choose a university from the list.", redirect_to)
    return university


def compose_edu_email(school: str, email_local: str, redirect_to: str) -> str:
    """Build a full address from the selected university and the typed local part.

    The domain is never taken from user input, so a student cannot register with
    an address at a university they did not select.
    """
    university = require_university(school, redirect_to)
    local = email_local.strip().lower()
    if "@" in local:
        raise ValidationError("Enter only the part before the @ — the domain comes from your university.", redirect_to)
    if not EMAIL_LOCAL_RE.fullmatch(local):
        raise ValidationError(
            "A student username may only contain letters, digits, dots, hyphens, underscores, percent or plus signs.",
            redirect_to,
        )
    return f"{local}@{university['domain']}"


def school_options(selected: str = "") -> str:
    """Render the university <select>.

    `data-domain` lets the page show the resulting @domain as soon as the student
    picks a university, without a round trip — see static/app.js.
    """
    options = []
    # An account whose school is no longer in the dataset keeps its value rather
    # than silently switching to whatever sits at the top of the list.
    if selected and selected not in UNIVERSITY_BY_NAME:
        options.append(
            f'<option value="{escape(selected)}" selected>{escape(display_school(selected))}</option>'
        )
    for university in UNIVERSITIES:
        name = university["name"]
        domain = university["domain"]
        is_selected = "selected" if name == selected else ""
        options.append(
            f'<option value="{escape(name)}" data-domain="{escape(domain)}" {is_selected}>'
            f"{escape(display_school(name))}</option>"
        )
    return "".join(options)
