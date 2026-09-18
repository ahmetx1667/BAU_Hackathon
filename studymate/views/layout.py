"""The page shell every response is wrapped in, plus shared form helpers."""

from __future__ import annotations

import sqlite3

from ..formatting import display_label, escape


def option_tags(options: list[str], selected: str = "") -> str:
    return "".join(
        f'<option value="{escape(item)}" {"selected" if item == selected else ""}>'
        f"{escape(display_label(item))}</option>"
        for item in options
    )


SIGNED_IN_NAV = """
        <a href="/dashboard">Dashboard</a>
        <a href="/posts">Sessions</a>
        <a href="/requests">Requests</a>
        <a href="/matches">Matches</a>
        <a href="/profile">Profile</a>
"""

SIGNED_OUT_NAV = """
        <a href="/security">Safety</a>
        <a class="nav-pill" href="/login">Sign in</a>
        <a class="button small" href="/register">Get started</a>
"""


def layout(title: str, content: str, user: sqlite3.Row | None, flash: str) -> str:
    nav = SIGNED_IN_NAV if user else SIGNED_OUT_NAV
    user_chip = f'<span class="user-chip">{escape(user["name"])}</span>' if user else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} | StudyMate</title>
  <link rel="stylesheet" href="/static/styles.css">
  <script defer src="/static/app.js"></script>
</head>
<body>
  <a class="skip-link" href="#content">Skip to content</a>
  <header class="topbar">
    <a class="brand" href="/" aria-label="StudyMate home"><span class="brand-mark"><img src="/static/logo.png" alt="StudyMate" width="36" height="36"></span><span>StudyMate</span></a>
    <nav aria-label="Main navigation">{nav}</nav>
    {user_chip}
  </header>
  <main id="content">
    {flash}
    {content}
  </main>
  <footer class="site-footer">
    <span>StudyMate &copy; 2026</span>
    <a href="/security">Safety and privacy</a>
  </footer>
</body>
</html>"""
