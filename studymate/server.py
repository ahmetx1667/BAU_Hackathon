"""The HTTP layer: request dispatch, sessions, CSRF, and every route handler.

Written directly on `http.server` rather than a framework, so the request cycle
is visible end to end: parse, authenticate, dispatch, render.
"""

from __future__ import annotations

import hmac
import secrets
import sqlite3
import time
from datetime import datetime, timedelta
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from .config import (
    COOKIE_NAME,
    COOKIE_SECURE,
    HOST,
    LOGIN_LOCKOUT_SECONDS,
    MAX_FAILED_LOGINS,
    MAX_REQUESTS_PER_HOUR,
    PORT,
    SESSION_DAYS,
    STATIC_DIR,
)
from .constants import LEVELS, LOCATIONS, MODES
from .database import db, expire_past_posts, init_db, seed_demo
from .errors import AuthRequired, CsrfError, ValidationError
from .formatting import (
    current_datetime_local,
    escape,
    normalize_phone,
    normalize_study_context,
    now_iso,
    parse_iso,
    utcnow,
    validate_level,
    validate_study_times,
)
from .matching import clear_cache_for_user
from .security import hash_password, token_hash, verify_password
from .universities import compose_edu_email, require_university
from .views.layout import layout
from .views.pages import (
    auth_page,
    dashboard_page,
    error_page,
    home_page,
    matches_page,
    page_not_found,
    post_form_page,
    posts_page,
    profile_page,
    requests_page,
    security_page,
)

CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; style-src 'self' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src 'self' data:; "
        "base-uri 'none'; frame-ancestors 'none'"
    ),
}

# Failed logins per client IP. In-memory, so it resets on restart and does not
# survive more than one process — enough to slow down guessing, not a substitute
# for a real rate limiter behind a proxy.
_failed_logins: dict[str, dict[str, float]] = {}


class StudyMateApp(BaseHTTPRequestHandler):
    server_version = "StudyMate/1.1"

    # ---- Dispatch ----------------------------------------------------------

    def do_GET(self) -> None:
        self.dispatch("GET")

    def do_POST(self) -> None:
        self.dispatch("POST")

    def log_message(self, fmt: str, *args: Any) -> None:
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        self.path_only = parsed.path.rstrip("/") or "/"
        self.query = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
        self.current_user, self.session = self.get_current_user()

        try:
            if self.path_only.startswith("/static/"):
                self.serve_static(self.path_only)
                return

            expire_past_posts()

            if method == "POST":
                self.form = self.read_form()
                # Sign-in and registration have no session yet, so no token to check.
                if self.path_only not in {"/login", "/register"}:
                    self.require_csrf()
                routes = {
                    "/register": self.post_register,
                    "/login": self.post_login,
                    "/logout": self.post_logout,
                    "/profile": self.post_profile,
                    "/posts/new": self.post_new_post,
                    "/requests/send": self.post_send_request,
                    "/requests/respond": self.post_respond_request,
                    "/reports": self.post_report,
                }
            else:
                routes = {
                    "/": self.get_home,
                    "/register": self.get_register,
                    "/login": self.get_login,
                    "/dashboard": self.get_dashboard,
                    "/profile": self.get_profile,
                    "/posts": self.get_posts,
                    "/posts/new": self.get_new_post,
                    "/requests": self.get_requests,
                    "/matches": self.get_matches,
                    "/security": self.get_security,
                }

            handler = routes.get(self.path_only)
            if not handler:
                self.render("Not found", page_not_found(), status=HTTPStatus.NOT_FOUND)
                return
            handler()

        except CsrfError:
            self.redirect("/dashboard", "Security check failed. Please try again.", "error")
        except AuthRequired:
            self.redirect("/login", "Sign in to continue.", "error")
        except ValidationError as exc:
            self.redirect(exc.redirect_to, str(exc), "error")
        except Exception as exc:
            self.render("Error", error_page(exc), status=HTTPStatus.INTERNAL_SERVER_ERROR)

    # ---- Request plumbing --------------------------------------------------

    def get_current_user(self) -> tuple[sqlite3.Row | None, sqlite3.Row | None]:
        cookie = SimpleCookie(self.headers.get("Cookie"))
        morsel = cookie.get(COOKIE_NAME)
        if not morsel:
            return None, None
        session_hash = token_hash(morsel.value)
        with db() as conn:
            session = conn.execute(
                "SELECT * FROM sessions WHERE token_hash = ?", (session_hash,)
            ).fetchone()
            if not session or parse_iso(session["expires_at"]) < utcnow():
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (session_hash,))
                return None, None
            user = conn.execute(
                "SELECT * FROM users WHERE id = ?", (session["user_id"],)
            ).fetchone()
            return user, session

    def read_form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")
        return {k: v[-1].strip() for k, v in parse_qs(raw, keep_blank_values=True).items()}

    def require_login(self) -> sqlite3.Row:
        if not self.current_user:
            raise AuthRequired()
        return self.current_user

    def require_csrf(self) -> None:
        if not self.session:
            raise CsrfError()
        token = self.form.get("csrf_token", "")
        if not hmac.compare_digest(token, self.session["csrf_token"]):
            raise CsrfError()

    def serve_static(self, path: str) -> None:
        relative_path = path.removeprefix("/static/").lstrip("/")
        file_path = STATIC_DIR / relative_path
        try:
            resolved_path = file_path.resolve()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        # The parents check is what stops ../../ escaping the static directory.
        if (
            not resolved_path.exists()
            or not resolved_path.is_file()
            or STATIC_DIR not in resolved_path.parents
        ):
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        body = resolved_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", CONTENT_TYPES.get(file_path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ---- Response helpers --------------------------------------------------

    def flash_from_query(self) -> str:
        message = self.query.get("flash", "")
        category = self.query.get("category", "info")
        if not message:
            return ""
        return f'<div class="flash {escape(category)}">{escape(message)}</div>'

    def csrf_input(self) -> str:
        if not self.session:
            return ""
        return f'<input type="hidden" name="csrf_token" value="{escape(self.session["csrf_token"])}">'

    def render(self, title: str, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = layout(title, content, self.current_user, self.flash_from_query())
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        for header, value in SECURITY_HEADERS.items():
            self.send_header(header, value)
        self.end_headers()
        self.wfile.write(encoded)

    def redirect(self, path: str, flash: str = "", category: str = "info") -> None:
        params = {"flash": flash, "category": category} if flash else {}
        location = path + (("?" + urlencode(params)) if params else "")
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    # ---- Sessions ----------------------------------------------------------

    def _session_cookie(self, value: str, expires: str) -> str:
        cookie = SimpleCookie()
        cookie[COOKIE_NAME] = value
        cookie[COOKIE_NAME]["path"] = "/"
        cookie[COOKIE_NAME]["httponly"] = True   # unreadable from JavaScript
        cookie[COOKIE_NAME]["samesite"] = "Lax"  # not sent on cross-site POSTs
        if COOKIE_SECURE:
            cookie[COOKIE_NAME]["secure"] = True
        cookie[COOKIE_NAME]["expires"] = expires
        return cookie.output(header="").strip()

    def set_session_cookie(self, token: str, expires_at: datetime) -> None:
        self.send_header(
            "Set-Cookie",
            self._session_cookie(token, expires_at.strftime("%a, %d %b %Y %H:%M:%S GMT")),
        )

    def clear_session_cookie(self) -> None:
        self.send_header("Set-Cookie", self._session_cookie("", "Thu, 01 Jan 1970 00:00:00 GMT"))

    def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(48)
        csrf = secrets.token_urlsafe(32)
        expires_at = utcnow() + timedelta(days=SESSION_DAYS)
        with db() as conn:
            conn.execute(
                """
                INSERT INTO sessions (user_id, token_hash, csrf_token, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, token_hash(token), csrf, expires_at.isoformat(timespec="seconds"), now_iso()),
            )
        return token

    def login_and_redirect(self, user_id: int, message: str) -> None:
        token = self.create_session(user_id)
        expires_at = utcnow() + timedelta(days=SESSION_DAYS)
        params = urlencode({"flash": message, "category": "success"})
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", f"/dashboard?{params}")
        self.set_session_cookie(token, expires_at)
        self.end_headers()

    # ---- Authentication routes --------------------------------------------

    def post_register(self) -> None:
        name = self.form.get("name", "")
        school = self.form.get("school", "")
        email = compose_edu_email(school, self.form.get("email_local", ""), "/register")
        phone = normalize_phone(self.form.get("phone", ""), "/register", required=True)
        password = self.form.get("password", "")
        if len(name) < 2 or len(password) < 8:
            raise ValidationError(
                "A name, university, phone number and a password of at least 8 characters are required.",
                "/register",
            )
        with db() as conn:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO users (name, email, password_hash, school, phone, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (name, email, hash_password(password), school, phone, now_iso()),
                )
            except sqlite3.IntegrityError:
                raise ValidationError("That email address is already registered.", "/register")
        self.login_and_redirect(cur.lastrowid, "Account created.")

    def post_login(self) -> None:
        ip = self.client_address[0]
        now = time.time()

        record = _failed_logins.get(ip)
        if record and record["locked_until"]:
            if now < record["locked_until"]:
                raise ValidationError(
                    "Too many failed attempts. Try again in 10 minutes.", "/login"
                )
            del _failed_logins[ip]

        school = self.form.get("school", "")
        email = compose_edu_email(school, self.form.get("email_local", ""), "/login")
        password = self.form.get("password", "")

        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if not user or not verify_password(password, user["password_hash"]):
            time.sleep(0.25)  # blunt the difference between "no such user" and "wrong password"
            attempt = _failed_logins.setdefault(ip, {"attempts": 0, "locked_until": 0})
            attempt["attempts"] += 1
            if attempt["attempts"] >= MAX_FAILED_LOGINS:
                attempt["locked_until"] = now + LOGIN_LOCKOUT_SECONDS
                raise ValidationError(
                    "Too many failed attempts. This address is blocked for 10 minutes.", "/login"
                )
            raise ValidationError("Incorrect email or password.", "/login")

        _failed_logins.pop(ip, None)
        self.login_and_redirect(user["id"], "Signed in.")

    def post_logout(self) -> None:
        if self.session:
            with db() as conn:
                conn.execute("DELETE FROM sessions WHERE id = ?", (self.session["id"],))
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.clear_session_cookie()
        self.end_headers()

    # ---- Page routes -------------------------------------------------------

    def get_home(self) -> None:
        if self.current_user:
            self.redirect("/dashboard")
            return
        self.render("StudyMate", home_page())

    def get_register(self) -> None:
        self.render("Create an account", auth_page("register"))

    def get_login(self) -> None:
        self.render("Sign in", auth_page("login"))

    def get_dashboard(self) -> None:
        user = self.require_login()
        cutoff = current_datetime_local()
        with db() as conn:
            open_posts = conn.execute(
                "SELECT COUNT(*) AS c FROM study_posts WHERE user_id = ? AND status = 'open' AND end_time > ?",
                (user["id"], cutoff),
            ).fetchone()["c"]
            incoming = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM study_requests r
                JOIN study_posts p ON p.id = r.post_id
                WHERE r.receiver_id = ? AND r.status = 'pending' AND p.status = 'open' AND p.end_time > ?
                """,
                (user["id"], cutoff),
            ).fetchone()["c"]
            matches = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM matches m
                JOIN study_posts p ON p.id = m.post_id
                WHERE (m.user1_id = ? OR m.user2_id = ?) AND p.end_time > ?
                """,
                (user["id"], user["id"], cutoff),
            ).fetchone()["c"]
            latest = conn.execute(
                """
                SELECT p.*, u.name, u.school
                FROM study_posts p
                JOIN users u ON u.id = p.user_id
                WHERE p.status = 'open' AND p.end_time > ? AND p.user_id != ?
                ORDER BY p.created_at DESC
                LIMIT 3
                """,
                (cutoff, user["id"]),
            ).fetchall()
        self.render(
            "Dashboard",
            dashboard_page(user, open_posts, incoming, matches, latest, self.csrf_input()),
        )

    def get_profile(self) -> None:
        user = self.require_login()
        self.render("Profile", profile_page(user, self.csrf_input()))

    def post_profile(self) -> None:
        user = self.require_login()
        bio = self.form.get("bio", "")[:500]
        skills = self.form.get("skills", "")[:300]
        school = self.form.get("school", "")[:120]
        require_university(school, "/profile")
        phone = normalize_phone(self.form.get("phone", ""), "/profile")
        with db() as conn:
            conn.execute(
                "UPDATE users SET school = ?, phone = ?, bio = ?, skills = ? WHERE id = ?",
                (school, phone, bio, skills, user["id"]),
            )
        # Scores were computed from the old profile, so they are stale now.
        clear_cache_for_user(user["id"])
        self.redirect("/profile", "Profile updated.", "success")

    def get_new_post(self) -> None:
        self.require_login()
        self.render("Post a session", post_form_page(self.csrf_input()))

    def post_new_post(self) -> None:
        user = self.require_login()
        topic = self.form.get("topic", "")[:100]
        if not topic:
            raise ValidationError("Give the session a subject.", "/posts/new")
        level = validate_level(self.form.get("level", ""), "/posts/new")
        location, mode, place = normalize_study_context(
            self.form.get("location", ""),
            self.form.get("mode", ""),
            self.form.get("place_preference", ""),
            "/posts/new",
        )
        start_time = self.form.get("start_time", "")
        end_time = self.form.get("end_time", "")
        validate_study_times(start_time, end_time)
        description = self.form.get("description", "")[:700]

        with db() as conn:
            conn.execute(
                """
                INSERT INTO study_posts
                (user_id, topic, level, location, mode, place_preference, start_time, end_time, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user["id"], topic, level, location, mode, place, start_time, end_time, description, now_iso()),
            )
        self.redirect("/posts", "Session published.", "success")

    def get_posts(self) -> None:
        user = self.require_login()
        filters = {
            "location": self.query.get("location", ""),
            "topic": self.query.get("topic", "").strip()[:100],
            "level": self.query.get("level", ""),
            "mode": self.query.get("mode", ""),
        }
        # Anything not in the known vocabulary is dropped rather than queried.
        for key, allowed in (("location", LOCATIONS), ("level", LEVELS), ("mode", MODES)):
            if filters[key] and filters[key] not in allowed:
                filters[key] = ""

        clauses = ["p.status = 'open'", "p.end_time > ?", "p.user_id != ?"]
        params: list[Any] = [current_datetime_local(), user["id"]]
        for column, key in (("p.location", "location"), ("p.level", "level"), ("p.mode", "mode")):
            if filters[key]:
                clauses.append(f"{column} = ?")
                params.append(filters[key])
        if filters["topic"]:
            clauses.append("(LOWER(p.topic) LIKE ? OR LOWER(p.description) LIKE ?)")
            like = f"%{filters['topic'].lower()}%"
            params.extend([like, like])

        with db() as conn:
            posts = conn.execute(
                f"""
                SELECT p.*, u.name, u.school, u.skills
                FROM study_posts p
                JOIN users u ON u.id = p.user_id
                WHERE {' AND '.join(clauses)}
                ORDER BY p.created_at DESC
                """,
                params,
            ).fetchall()
            request_rows = conn.execute(
                "SELECT post_id, status FROM study_requests WHERE sender_id = ?",
                (user["id"],),
            ).fetchall()

        request_status = {row["post_id"]: row["status"] for row in request_rows}
        self.render(
            "Sessions", posts_page(user, posts, filters, request_status, self.csrf_input())
        )

    # ---- Requests and matches ---------------------------------------------

    def post_send_request(self) -> None:
        user = self.require_login()
        post_id = int(self.form.get("post_id", "0") or "0")
        message = self.form.get("message", "")[:240]
        with db() as conn:
            post = conn.execute(
                "SELECT * FROM study_posts WHERE id = ? AND status = 'open' AND end_time > ?",
                (post_id, current_datetime_local()),
            ).fetchone()
            if not post:
                raise ValidationError("That session no longer exists or has ended.", "/posts")
            if post["user_id"] == user["id"]:
                raise ValidationError("You cannot request to join your own session.", "/posts")

            one_hour_ago = (utcnow() - timedelta(hours=1)).isoformat(timespec="seconds")
            sent_count = conn.execute(
                "SELECT COUNT(*) AS c FROM study_requests WHERE sender_id = ? AND created_at >= ?",
                (user["id"], one_hour_ago),
            ).fetchone()["c"]
            if sent_count >= MAX_REQUESTS_PER_HOUR:
                raise ValidationError(
                    f"Spam protection: at most {MAX_REQUESTS_PER_HOUR} requests per hour.", "/posts"
                )

            duplicate = conn.execute(
                """
                SELECT id FROM study_requests
                WHERE post_id = ? AND sender_id = ? AND status IN ('pending', 'accepted')
                """,
                (post_id, user["id"]),
            ).fetchone()
            if duplicate:
                raise ValidationError("You have already requested this session.", "/posts")

            conn.execute(
                """
                INSERT INTO study_requests (post_id, sender_id, receiver_id, message, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """,
                (post_id, user["id"], post["user_id"], message, now_iso(), now_iso()),
            )
        self.redirect("/posts", "Request sent.", "success")

    def get_requests(self) -> None:
        user = self.require_login()
        cutoff = current_datetime_local()
        with db() as conn:
            incoming = conn.execute(
                """
                SELECT r.*, p.topic, p.location, p.start_time, p.end_time,
                       u.name AS sender_name, u.school, u.skills
                FROM study_requests r
                JOIN study_posts p ON p.id = r.post_id
                JOIN users u ON u.id = r.sender_id
                WHERE r.receiver_id = ? AND p.end_time > ?
                ORDER BY r.created_at DESC
                """,
                (user["id"], cutoff),
            ).fetchall()
            outgoing = conn.execute(
                """
                SELECT r.*, p.topic, p.location, p.start_time, p.end_time, u.name AS receiver_name
                FROM study_requests r
                JOIN study_posts p ON p.id = r.post_id
                JOIN users u ON u.id = r.receiver_id
                WHERE r.sender_id = ? AND p.end_time > ?
                ORDER BY r.created_at DESC
                """,
                (user["id"], cutoff),
            ).fetchall()
        self.render("Requests", requests_page(incoming, outgoing, self.csrf_input()))

    def post_respond_request(self) -> None:
        user = self.require_login()
        request_id = int(self.form.get("request_id", "0") or "0")
        action = self.form.get("action", "")
        if action not in {"accepted", "rejected"}:
            raise ValidationError("Unknown action.", "/requests")

        with db() as conn:
            req = conn.execute(
                """
                SELECT r.*, p.end_time
                FROM study_requests r
                JOIN study_posts p ON p.id = r.post_id
                WHERE r.id = ?
                """,
                (request_id,),
            ).fetchone()
            # The receiver check is the authorisation: only the person the request
            # was sent to can answer it.
            if not req or req["receiver_id"] != user["id"] or req["status"] != "pending":
                raise ValidationError("That request no longer needs an answer.", "/requests")
            if req["end_time"] <= current_datetime_local():
                raise ValidationError("That session has already ended.", "/requests")

            conn.execute(
                "UPDATE study_requests SET status = ?, updated_at = ? WHERE id = ?",
                (action, now_iso(), request_id),
            )
            if action == "accepted":
                conn.execute(
                    """
                    INSERT OR IGNORE INTO matches (request_id, post_id, user1_id, user2_id, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (request_id, req["post_id"], req["receiver_id"], req["sender_id"], now_iso()),
                )

        message = "You matched." if action == "accepted" else "Request declined."
        self.redirect("/requests", message, "success")

    def get_matches(self) -> None:
        user = self.require_login()
        cutoff = current_datetime_local()
        with db() as conn:
            matches = conn.execute(
                """
                SELECT m.*, p.topic, p.location, p.mode, p.place_preference, p.start_time, p.end_time,
                       owner.name AS owner_name, partner.name AS partner_name,
                       CASE WHEN m.user1_id = ? THEN m.user2_id ELSE m.user1_id END AS other_id,
                       CASE WHEN m.user1_id = ? THEN partner.name ELSE owner.name END AS other_name,
                       CASE WHEN m.user1_id = ? THEN partner.phone ELSE owner.phone END AS other_phone
                FROM matches m
                JOIN study_posts p ON p.id = m.post_id
                JOIN users owner ON owner.id = m.user1_id
                JOIN users partner ON partner.id = m.user2_id
                WHERE (m.user1_id = ? OR m.user2_id = ?) AND p.end_time > ?
                ORDER BY m.created_at DESC
                """,
                (user["id"], user["id"], user["id"], user["id"], user["id"], cutoff),
            ).fetchall()
        self.render("Matches", matches_page(user, matches, self.csrf_input()))

    def post_report(self) -> None:
        user = self.require_login()
        reported_user_id = int(self.form.get("reported_user_id", "0") or "0")
        reason = self.form.get("reason", "")[:500]
        if reported_user_id == user["id"] or len(reason) < 5:
            raise ValidationError("Give at least a few words describing what happened.", "/matches")
        with db() as conn:
            if not conn.execute("SELECT id FROM users WHERE id = ?", (reported_user_id,)).fetchone():
                raise ValidationError("That user does not exist.", "/matches")
            conn.execute(
                "INSERT INTO reports (reporter_id, reported_user_id, reason, created_at) VALUES (?, ?, ?, ?)",
                (user["id"], reported_user_id, reason, now_iso()),
            )
        self.redirect("/matches", "Report submitted.", "success")

    def get_security(self) -> None:
        self.render("Safety", security_page())


def main() -> None:
    init_db()
    seed_demo()
    server = ThreadingHTTPServer((HOST, PORT), StudyMateApp)
    print(f"StudyMate running at http://{HOST}:{PORT}")
    server.serve_forever()
