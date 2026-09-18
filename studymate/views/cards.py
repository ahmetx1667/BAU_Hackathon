"""The repeated card components: sessions, incoming requests and matches."""

from __future__ import annotations

import sqlite3

from ..constants import DEFAULT_PUBLIC_PLACE, PUBLIC_PLACES
from ..formatting import (
    display_label,
    display_school,
    display_time_range,
    escape,
    meta_spans,
    status_label,
)
from ..matching import match_score


def post_card(user: sqlite3.Row, post: sqlite3.Row, status: str | None, csrf: str) -> str:
    """One open study session, with this student's match score against it."""
    score, reason = match_score(user, post)

    # Once a request exists, the form is replaced by its status — so a student
    # cannot send a second request to the same session from the same page.
    if status:
        request_area = (
            f'<span class="status {escape(status)}">Request: {escape(status_label(status))}</span>'
        )
    else:
        request_area = f"""
        <form method="post" action="/requests/send" class="inline-form">
          {csrf}
          <input type="hidden" name="post_id" value="{post["id"]}">
          <input name="message" maxlength="240" placeholder="Short message (optional)">
          <button class="button small" type="submit">Send request</button>
        </form>
        """

    meta = meta_spans([
        post["location"],
        post["mode"],
        post["place_preference"],
        display_time_range(post["start_time"], post["end_time"]),
    ])
    return f"""
    <article class="card">
      <div class="card-top">
        <div>
          <p class="card-kicker">{escape(post["name"])} - {escape(display_school(post["school"]))}</p>
          <h3>{escape(post["topic"])}</h3>
        </div>
        <span class="badge">Match {score}%</span>
      </div>
      <p>Looking for a partner at <strong>{escape(display_label(post["level"]))}</strong> level.</p>
      <p>{escape(post["description"])}</p>
      <div class="meta">{meta}</div>
      <p class="hint">{escape(reason)}</p>
      {request_area}
    </article>
    """


def compact_post_card(post: sqlite3.Row) -> str:
    return f"""
    <article class="card compact">
      <p class="card-kicker">{escape(post["name"])} - {escape(display_school(post["school"]))}</p>
      <h3>{escape(post["topic"])}</h3>
      <p>{escape(display_label(post["location"]))} / {escape(display_time_range(post["start_time"], post["end_time"]))}</p>
    </article>
    """


def incoming_request_card(row: sqlite3.Row, csrf: str) -> str:
    if row["status"] == "pending":
        controls = f"""
        <form method="post" action="/requests/respond" class="row-actions">
          {csrf}
          <input type="hidden" name="request_id" value="{row["id"]}">
          <button class="button small" name="action" value="accepted" type="submit">Accept</button>
          <button class="ghost danger small" name="action" value="rejected" type="submit">Decline</button>
        </form>
        """
    else:
        controls = f'<span class="status {escape(row["status"])}">{escape(status_label(row["status"]))}</span>'

    meta = meta_spans([row["location"], display_time_range(row["start_time"], row["end_time"])])
    return f"""
    <article class="card">
      <h3>{escape(row["sender_name"])}</h3>
      <p class="muted">{escape(display_school(row["school"]))} - {escape(row["skills"])}</p>
      <p>Wants to join your <strong>{escape(row["topic"])}</strong> session.</p>
      <p class="hint">{escape(row["message"])}</p>
      <div class="meta">{meta}</div>
      {controls}
    </article>
    """


def match_card(user: sqlite3.Row, row: sqlite3.Row, csrf: str) -> str:
    """A confirmed match — the only place a phone number is ever shown."""
    suggestion = PUBLIC_PLACES.get(row["location"], DEFAULT_PUBLIC_PLACE)
    phone = row["other_phone"] or "No phone number saved"
    meta = meta_spans([
        row["mode"],
        row["place_preference"],
        display_time_range(row["start_time"], row["end_time"]),
    ])
    return f"""
    <article class="card">
      <span class="badge">Matched</span>
      <h3>{escape(row["other_name"])}</h3>
      <p><strong>{escape(row["topic"])}</strong> - {escape(display_label(row["location"]))}</p>
      <div class="meta">{meta}</div>
      <p class="contact-line"><strong>Phone:</strong> {escape(phone)}</p>
      <p class="hint">Suggested meeting place: {escape(suggestion)}</p>
      <details>
        <summary>Report</summary>
        <form method="post" action="/reports" class="stack mini">
          {csrf}
          <input type="hidden" name="reported_user_id" value="{row["other_id"]}">
          <textarea name="reason" rows="3" required placeholder="What happened?"></textarea>
          <button class="ghost danger small" type="submit">Submit report</button>
        </form>
      </details>
    </article>
    """
