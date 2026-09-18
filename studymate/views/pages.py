"""Full-page templates, one function per route."""

from __future__ import annotations

import sqlite3
from datetime import timedelta

from ..constants import LEVELS, LOCATIONS, MODES, PLACES
from ..formatting import (
    datetime_local,
    display_time_range,
    escape,
    localnow,
    status_label,
)
from ..universities import default_domain, default_school, school_options
from .cards import compact_post_card, incoming_request_card, match_card, post_card
from .layout import option_tags


def home_page() -> str:
    return """
    <section class="hero">
      <div class="hero-copy">
        <p class="eyebrow">A study network for university students</p>
        <h1>Find a study partner by subject, level and district.</h1>
        <p class="lead">StudyMate matches students through university verification, a safe meeting suggestion and a request you have to accept.</p>
        <div class="actions">
          <a class="button" href="/register">Get started</a>
          <a class="ghost" href="/login">Try a demo account</a>
        </div>
        <div class="trust-row" aria-label="Trust signals">
          <span>🎓 University verified</span>
          <span>🔒 Secure by default</span>
          <span>📱 Privacy first</span>
        </div>
      </div>
      <div class="hero-panel">
        <div class="match-card preview-card">
          <div class="preview-head">
            <div>
              <span class="badge">Match 87%</span>
              <h3>Organic Chemistry with Ece</h3>
            </div>
            <span class="avatar">ED</span>
          </div>
          <p>Looking for a partner to work through organic chemistry reactions around Beşiktaş.</p>
          <div class="meta">
            <span>Intermediate</span>
            <span>Library</span>
            <span>Today 18:00</span>
          </div>
          <div class="safe-box">
            Phone numbers and exact addresses stay hidden until both sides accept. A safe meeting place is suggested once you match.
          </div>
        </div>
      </div>
    </section>
    <section class="stats landing-stats">
      <article><strong>3 steps</strong><span>Post, get a request, match</span></article>
      <article><strong>Scored</strong><span>Automatic match rating</span></article>
      <article><strong>Verified</strong><span>University email required</span></article>
    </section>
    <section class="features">
      <article><span class="feature-icon">🎯</span><h3>Specific, not random</h3><p>No swiping. Sessions are posted by subject, level, time and district.</p></article>
      <article><span class="feature-icon">🛡️</span><h3>You stay in control</h3><p>No phone number is shown until you accept, and the first meeting is suggested somewhere public.</p></article>
      <article><span class="feature-icon">⚡</span><h3>Matched by interest</h3><p>Every session is scored against what you are actually studying.</p></article>
    </section>
    """


def auth_page(mode: str) -> str:
    is_register = mode == "register"
    action = "/register" if is_register else "/login"
    title = "Create an account" if is_register else "Sign in"

    extra = (
        """
        <label>Name
          <input name="name" required minlength="2" autocomplete="name">
        </label>
        <label>Phone
          <input name="phone" required inputmode="tel" autocomplete="tel" placeholder="+90 555 123 45 67">
        </label>
        <p class="hint">Your phone number is only ever shown on a match you accepted.</p>
        """
        if is_register
        else ""
    )
    helper = (
        '<p class="form-intro">Pick your university, then enter only the part of your student email before the @. The domain is filled in for you.</p>'
        if is_register
        else '<p class="form-intro">Demo accounts: ahmet @bogazici.edu.tr / Ahmet2026! or ece @itu.edu.tr / Ece2026!</p>'
    )
    alternate = (
        '<p class="auth-switch">Already have an account? <a href="/login">Sign in</a></p>'
        if is_register
        else '<p class="auth-switch">No account yet? <a href="/register">Create one</a></p>'
    )
    password_autocomplete = "new-password" if is_register else "current-password"

    return f"""
    <section class="form-wrap narrow">
      <h1>{title}</h1>
      {helper}
      <form method="post" action="{action}" class="stack">
        {extra}
        <label>University
          <select name="school" class="js-school-select" data-domain-target="email-domain" required>
            {school_options(default_school())}
          </select>
        </label>
        <label>Student email
          <span class="email-composer">
            <input name="email_local" required autocomplete="username" placeholder="student.number or first.last" pattern="[A-Za-z0-9._%+\\-]{{1,64}}">
            <span class="email-domain">@<span id="email-domain">{escape(default_domain())}</span></span>
          </span>
        </label>
        <label>Password
          <input type="password" name="password" required minlength="8" autocomplete="{password_autocomplete}">
        </label>
        <button class="button" type="submit">{title}</button>
      </form>
      {alternate}
    </section>
    """


def dashboard_page(
    user: sqlite3.Row,
    open_posts: int,
    incoming: int,
    matches: int,
    latest: list[sqlite3.Row],
    csrf: str,
) -> str:
    cards = "".join(compact_post_card(row) for row in latest) or '<p class="empty">No new sessions right now.</p>'
    return f"""
    <section class="page-head">
      <div>
        <p class="eyebrow">Hello {escape(user["name"])}</p>
        <h1>Your study dashboard</h1>
      </div>
      <form method="post" action="/logout">{csrf}<button class="ghost danger" type="submit">Sign out</button></form>
    </section>
    <section class="stats">
      <article><strong>{open_posts}</strong><span>Open sessions</span></article>
      <article><strong>{incoming}</strong><span>Pending requests</span></article>
      <article><strong>{matches}</strong><span>Active matches</span></article>
    </section>
    <section class="quick-actions">
      <a class="button" href="/posts/new">Post a session</a>
      <a class="ghost" href="/posts">Browse nearby sessions</a>
    </section>
    <section>
      <div class="section-title">
        <div>
          <p class="eyebrow">Discover</p>
          <h2>Latest sessions</h2>
        </div>
        <a class="text-link" href="/posts">See all</a>
      </div>
      <div class="grid">{cards}</div>
    </section>
    """


def profile_page(user: sqlite3.Row, csrf: str) -> str:
    return f"""
    <section class="form-wrap">
      <h1>Profile</h1>
      <p class="form-intro">Add the subjects you are working on — match scores are calculated from this.</p>
      <form method="post" action="/profile" class="stack">
        {csrf}
        <label>University
          <select name="school" required>
            {school_options(user["school"])}
          </select>
        </label>
        <label>Phone
          <input name="phone" value="{escape(user["phone"])}" inputmode="tel" autocomplete="tel" placeholder="+90 555 123 45 67">
        </label>
        <p class="hint">Only shown to someone once you have accepted a match with them.</p>
        <label>Interests
          <input name="skills" value="{escape(user["skills"])}" maxlength="300" placeholder="Physics, Mathematics, Chemistry">
        </label>
        <label>Bio
          <textarea name="bio" rows="5" maxlength="500" placeholder="What are you studying?">{escape(user["bio"])}</textarea>
        </label>
        <button class="button" type="submit">Save</button>
      </form>
    </section>
    """


def post_form_page(csrf: str) -> str:
    start = datetime_local()
    end = (localnow() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
    return f"""
    <section class="form-wrap">
      <h1>Post a study session</h1>
      <p class="form-intro">Be specific about the subject and the time — that is what the match score is calculated from.</p>
      <form method="post" action="/posts/new" class="stack js-post-form">
        {csrf}
        <label>Subject
          <input name="topic" required maxlength="100" placeholder="Classical Mechanics">
        </label>
        <div class="two-col">
          <label>Level
            <select name="level">{option_tags(LEVELS)}</select>
          </label>
          <label>District
            <select name="location">{option_tags(LOCATIONS)}</select>
          </label>
        </div>
        <div class="two-col">
          <label>Format
            <select name="mode">{option_tags(MODES)}</select>
          </label>
          <label>Venue
            <select name="place_preference">{option_tags(PLACES)}</select>
          </label>
        </div>
        <div class="two-col">
          <label>Starts
            <input type="datetime-local" name="start_time" value="{start}" required>
          </label>
          <label>Ends
            <input type="datetime-local" name="end_time" value="{end}" required>
          </label>
        </div>
        <label>Description
          <textarea name="description" rows="5" maxlength="700" placeholder="Preparing for a physics exam, want to work through problems together."></textarea>
        </label>
        <button class="button" type="submit">Publish</button>
      </form>
    </section>
    """


def posts_page(
    user: sqlite3.Row,
    posts: list[sqlite3.Row],
    filters: dict[str, str],
    request_status: dict[int, str],
    csrf: str,
) -> str:
    post_cards = "".join(post_card(user, row, request_status.get(row["id"]), csrf) for row in posts)
    if not post_cards:
        post_cards = '<p class="empty">No sessions match those filters. Post your own to start one.</p>'
    return f"""
    <section class="page-head">
      <div>
        <p class="eyebrow">Matched by district</p>
        <h1>Nearby sessions</h1>
      </div>
      <a class="button" href="/posts/new">New session</a>
    </section>
    <form method="get" action="/posts" class="filters">
      <input name="topic" value="{escape(filters["topic"])}" placeholder="Search a subject">
      <select name="location"><option value="">All districts</option>{option_tags(LOCATIONS, filters["location"])}</select>
      <select name="level"><option value="">All levels</option>{option_tags(LEVELS, filters["level"])}</select>
      <select name="mode"><option value="">All formats</option>{option_tags(MODES, filters["mode"])}</select>
      <button class="ghost" type="submit">Filter</button>
    </form>
    <section class="grid">{post_cards}</section>
    """


def requests_page(incoming: list[sqlite3.Row], outgoing: list[sqlite3.Row], csrf: str) -> str:
    incoming_html = "".join(incoming_request_card(row, csrf) for row in incoming) or '<p class="empty">No incoming requests.</p>'
    outgoing_html = "".join(
        f"""
        <article class="card compact">
          <h3>{escape(row["receiver_name"])}</h3>
          <p>{escape(row["topic"])} - {escape(row["location"])}</p>
          <p class="muted">{escape(display_time_range(row["start_time"], row["end_time"]))}</p>
          <span class="status {escape(row["status"])}">{escape(status_label(row["status"]))}</span>
        </article>
        """
        for row in outgoing
    ) or '<p class="empty">You have not sent any requests.</p>'
    return f"""
    <section class="page-head"><h1>Requests</h1></section>
    <section>
      <h2>Incoming</h2>
      <div class="grid">{incoming_html}</div>
    </section>
    <section>
      <h2>Sent</h2>
      <div class="grid">{outgoing_html}</div>
    </section>
    """


def matches_page(user: sqlite3.Row, matches: list[sqlite3.Row], csrf: str) -> str:
    cards = "".join(match_card(user, row, csrf) for row in matches) or '<p class="empty">No matches yet.</p>'
    return f"""
    <section class="page-head"><h1>Matches</h1></section>
    <div class="safety-note">
      Do not share your exact address. Meet somewhere public and busy the first time, and report anything that feels wrong.
    </div>
    <section class="grid">{cards}</section>
    """


def security_page() -> str:
    return """
    <section class="form-wrap">
      <h1>Safety and privacy</h1>
      <p class="form-intro">How StudyMate protects you:</p>
      <ul class="checklist">
        <li>🎓 Registration requires a university email address, so every account belongs to a real student.</li>
        <li>🔒 Passwords are salted and hashed with PBKDF2, never stored as plain text.</li>
        <li>📍 Your exact address is never shared — only a district, or an online session.</li>
        <li>📱 Your phone number appears only after both sides accept a match.</li>
        <li>🛡️ Spam protection limits each account to 10 requests per hour.</li>
        <li>📍 Every match comes with a suggested public meeting place.</li>
        <li>🚨 You can report anyone, from the match itself.</li>
      </ul>
    </section>
    """


def page_not_found() -> str:
    return '<section class="form-wrap"><h1>404</h1><p>That page does not exist.</p><a class="button" href="/">Go home</a></section>'


def error_page(exc: Exception) -> str:
    return f"""
    <section class="form-wrap">
      <h1>Something went wrong</h1>
      <p class="muted">{escape(exc)}</p>
      <a class="button" href="/dashboard">Back to the dashboard</a>
    </section>
    """
