from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse


ROOT = Path(__file__).resolve().parent


def load_env_file(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file()

INSTANCE_DIR = ROOT / "instance"
STATIC_DIR = ROOT / "static"
UNIVERSITIES_PATH = ROOT / "data" / "turkish_universities.json"
COOKIE_NAME = "studymate_session"
SESSION_DAYS = 7
PBKDF2_ITERATIONS = 310_000
EMAIL_LOCAL_RE = re.compile(r"^[a-z0-9._%+-]{1,64}$")
COOKIE_SECURE = os.environ.get("STUDYMATE_COOKIE_SECURE", "").lower() in {"1", "true", "yes", "on"}


def runtime_path(env_name: str, default: Path) -> Path:
    configured = os.environ.get(env_name)
    if not configured:
        return default
    path = Path(configured).expanduser()
    return path if path.is_absolute() else ROOT / path


DB_PATH = runtime_path("STUDYMATE_DB_PATH", INSTANCE_DIR / "studymate.sqlite3")
SECRET_PATH = runtime_path("STUDYMATE_SECRET_PATH", INSTANCE_DIR / "secret.key")

LOCATIONS = [
    "Besiktas",
    "Kadikoy",
    "Sisli",
    "Bakirkoy",
    "Uskudar",
    "Online",
]
LEVELS = ["Beginner", "Intermediate", "Advanced"]
MODES = ["Yuz yuze", "Online"]
PLACES = ["Kafe", "Kutuphane", "Kampus", "Online"]
PUBLIC_PLACES = {
    "Besiktas": "Besiktas ilce kutuphanesi veya kalabalik bir kafe",
    "Kadikoy": "Kadikoy belediye kutuphanesi veya Moda civari kalabalik bir kafe",
    "Sisli": "Mecidiyekoy civari halka acik calisma alani",
    "Bakirkoy": "Bakirkoy halk kutuphanesi veya kalabalik bir kafe",
    "Uskudar": "Uskudar kutuphanesi veya sahil civari kalabalik bir kafe",
    "Online": "Online gorusme; kisisel telefon/adres paylasmadan once eslesmeyi netlestirin",
}
STOP_WORDS = {
    "ve",
    "ile",
    "bir",
    "icin",
    "ben",
    "sen",
    "bugun",
    "saat",
    "calisma",
    "calisiyorum",
    "istiyorum",
    "proje",
    "yapmak",
    "learn",
    "the",
    "and",
    "for",
    "with",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utcnow().isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def slug_words(text: str) -> set[str]:
    cleaned = []
    for ch in text.lower():
        cleaned.append(ch if ch.isalnum() else " ")
    words = {w for w in "".join(cleaned).split() if len(w) > 2}
    return words - STOP_WORDS


def normalize_phone(value: str) -> str:
    value = " ".join(value.strip().split())[:32]
    allowed = set("+0123456789 ()-")
    if value and (any(ch not in allowed for ch in value) or sum(ch.isdigit() for ch in value) < 10):
        raise ValidationError("Telefon numarasi en az 10 rakam icermeli ve sadece +, bosluk, tire, parantez kullanmali.", "/profile")
    return value


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


def require_university(name: str, redirect_to: str) -> dict[str, str]:
    university = UNIVERSITY_BY_NAME.get(name)
    if not university:
        raise ValidationError("Listeden gecerli bir universite secmelisin.", redirect_to)
    return university


def compose_edu_email(school: str, email_local: str, redirect_to: str) -> str:
    university = require_university(school, redirect_to)
    local = email_local.strip().lower()
    if "@" in local:
        raise ValidationError("Email alanina sadece @ oncesindeki ogrenci kullanici adini yaz.", redirect_to)
    if not EMAIL_LOCAL_RE.fullmatch(local):
        raise ValidationError("Edu email kullanici adi sadece harf, rakam, nokta, tire, alt tire, yuzde veya arti icerebilir.", redirect_to)
    return f"{local}@{university['domain']}"


def school_options(selected: str = "") -> str:
    options = []
    if selected and selected not in UNIVERSITY_BY_NAME:
        options.append(f'<option value="{escape(selected)}" selected>{escape(selected)}</option>')
    for university in UNIVERSITIES:
        name = university["name"]
        domain = university["domain"]
        is_selected = "selected" if name == selected else ""
        options.append(
            f'<option value="{escape(name)}" data-domain="{escape(domain)}" {is_selected}>{escape(name)}</option>'
        )
    return "".join(options)


def option_tags(options: list[str], selected: str = "") -> str:
    return "".join(
        f'<option value="{escape(item)}" {"selected" if item == selected else ""}>{escape(item)}</option>'
        for item in options
    )


def datetime_local(value: str | None = None) -> str:
    if value:
        return value[:16]
    return (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")


def display_datetime(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value.replace("T", " ")
    return parsed.strftime("%d.%m %H:%M")


def display_time_range(start: str, end: str) -> str:
    return f"{display_datetime(start)} - {display_datetime(end)}"


def validate_study_times(start_time: str, end_time: str) -> None:
    try:
        start = datetime.fromisoformat(start_time)
        end = datetime.fromisoformat(end_time)
    except ValueError:
        raise ValidationError("Baslangic ve bitis zamani gecerli olmali.", "/posts/new")
    if start >= end:
        raise ValidationError("Bitis zamani baslangictan sonra olmali.", "/posts/new")
    if start < datetime.now() - timedelta(minutes=5):
        raise ValidationError("Gecmis zamanli ilan olusturamazsin.", "/posts/new")


def get_secret() -> bytes:
    SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
    env_secret = os.environ.get("STUDYMATE_SECRET_KEY")
    if env_secret:
        return env_secret.encode()
    if not SECRET_PATH.exists():
        SECRET_PATH.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        try:
            SECRET_PATH.chmod(0o600)
        except OSError:
            pass
    return SECRET_PATH.read_text(encoding="utf-8").strip().encode()


SECRET_KEY = get_secret()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(derived).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_b64, derived_b64 = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(derived_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                school TEXT NOT NULL,
                phone TEXT NOT NULL DEFAULT '',
                bio TEXT NOT NULL DEFAULT '',
                skills TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                csrf_token TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS study_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                topic TEXT NOT NULL,
                level TEXT NOT NULL,
                location TEXT NOT NULL,
                mode TEXT NOT NULL,
                place_preference TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS study_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (post_id) REFERENCES study_posts(id) ON DELETE CASCADE,
                FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (receiver_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL UNIQUE,
                post_id INTEGER NOT NULL,
                user1_id INTEGER NOT NULL,
                user2_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (request_id) REFERENCES study_requests(id) ON DELETE CASCADE,
                FOREIGN KEY (post_id) REFERENCES study_posts(id) ON DELETE CASCADE,
                FOREIGN KEY (user1_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (user2_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id INTEGER NOT NULL,
                reported_user_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (reporter_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (reported_user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_posts_search ON study_posts(location, topic, level, mode, status);
            CREATE INDEX IF NOT EXISTS idx_requests_receiver ON study_requests(receiver_id, status);
            CREATE INDEX IF NOT EXISTS idx_requests_sender ON study_requests(sender_id, status);
            """
        )
        user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "phone" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN phone TEXT NOT NULL DEFAULT ''")
        demo_updates = [
            ("ahmet@bogazici.edu.tr", "Boğaziçi University", "ahmet@demo.test"),
            ("ece@itu.edu.tr", "Istanbul Technical University", "ece@demo.test"),
            ("mert@marmara.edu.tr", "Marmara University", "mert@demo.test"),
        ]
        for new_email, new_school, old_email in demo_updates:
            conn.execute(
                "UPDATE users SET email = ?, school = ? WHERE email = ?",
                (new_email, new_school, old_email),
            )


def seed_demo() -> None:
    with db() as conn:
        existing = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if existing:
            return
        users = [
            ("Ahmet Kaya", "ahmet@bogazici.edu.tr", "Ahmet2026!", "Boğaziçi University", "+90 555 100 10 10", "Backend ogreniyorum.", "Python, Flask, SQL"),
            ("Ece Demir", "ece@itu.edu.tr", "Ece2026!", "Istanbul Technical University", "+90 555 200 20 20", "API gelistirmek istiyorum.", "Python, Flask, Backend"),
            ("Mert Yilmaz", "mert@marmara.edu.tr", "Mert2026!", "Marmara University", "+90 555 300 30 30", "Frontend odakliyim.", "React, TypeScript, UI"),
        ]
        for name, email, password, school, phone, bio, skills in users:
            conn.execute(
                """
                INSERT INTO users (name, email, password_hash, school, phone, bio, skills, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (name, email, hash_password(password), school, phone, bio, skills, now_iso()),
            )
        ahmet = conn.execute("SELECT id FROM users WHERE email = ?", ("ahmet@bogazici.edu.tr",)).fetchone()["id"]
        ece = conn.execute("SELECT id FROM users WHERE email = ?", ("ece@itu.edu.tr",)).fetchone()["id"]
        mert = conn.execute("SELECT id FROM users WHERE email = ?", ("mert@marmara.edu.tr",)).fetchone()["id"]
        start = datetime_local()
        end = (datetime.now() + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")
        posts = [
            (ahmet, "Python Flask", "Beginner", "Besiktas", "Yuz yuze", "Kutuphane", start, end, "Flask ile guvenli API ve SQLite calismak istiyorum."),
            (ece, "Backend API", "Intermediate", "Besiktas", "Yuz yuze", "Kafe", start, end, "Python ve Flask uzerinden endpoint tasarimi calisiyorum."),
            (mert, "React", "Intermediate", "Kadikoy", "Online", "Online", start, end, "React component mimarisi ve state management calisacagim."),
        ]
        for post in posts:
            conn.execute(
                """
                INSERT INTO study_posts
                (user_id, topic, level, location, mode, place_preference, start_time, end_time, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*post, now_iso()),
            )


class StudyMateApp(BaseHTTPRequestHandler):
    server_version = "StudyMate/1.1"

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
            if method == "POST":
                self.form = self.read_form()
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
                self.render("Sayfa bulunamadi", page_not_found(), status=HTTPStatus.NOT_FOUND)
                return
            handler()
        except CsrfError:
            self.redirect("/dashboard", "Guvenlik dogrulamasi basarisiz. Lutfen tekrar deneyin.", "error")
        except AuthRequired:
            self.redirect("/login", "Devam etmek icin giris yapmalisin.", "error")
        except ValidationError as exc:
            self.redirect(exc.redirect_to, str(exc), "error")
        except Exception as exc:
            self.render("Hata", error_page(exc), status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def get_current_user(self) -> tuple[sqlite3.Row | None, sqlite3.Row | None]:
        cookie = SimpleCookie(self.headers.get("Cookie"))
        morsel = cookie.get(COOKIE_NAME)
        if not morsel:
            return None, None
        session_hash = token_hash(morsel.value)
        with db() as conn:
            session = conn.execute(
                "SELECT * FROM sessions WHERE token_hash = ?",
                (session_hash,),
            ).fetchone()
            if not session or parse_iso(session["expires_at"]) < utcnow():
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (session_hash,))
                return None, None
            user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
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
        if not resolved_path.exists() or not resolved_path.is_file() or STATIC_DIR not in resolved_path.parents:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_types = {
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
        }
        content_type = content_types.get(file_path.suffix, "application/octet-stream")
        body = resolved_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

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
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(encoded)

    def redirect(self, path: str, flash: str = "", category: str = "info") -> None:
        params = {}
        if flash:
            params = {"flash": flash, "category": category}
        location = path + (("?" + urlencode(params)) if params else "")
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def set_session_cookie(self, token: str, expires_at: datetime) -> None:
        cookie = SimpleCookie()
        cookie[COOKIE_NAME] = token
        cookie[COOKIE_NAME]["path"] = "/"
        cookie[COOKIE_NAME]["httponly"] = True
        cookie[COOKIE_NAME]["samesite"] = "Lax"
        if COOKIE_SECURE:
            cookie[COOKIE_NAME]["secure"] = True
        cookie[COOKIE_NAME]["expires"] = expires_at.strftime("%a, %d %b %Y %H:%M:%S GMT")
        self.send_header("Set-Cookie", cookie.output(header="").strip())

    def clear_session_cookie(self) -> None:
        cookie = SimpleCookie()
        cookie[COOKIE_NAME] = ""
        cookie[COOKIE_NAME]["path"] = "/"
        cookie[COOKIE_NAME]["httponly"] = True
        cookie[COOKIE_NAME]["samesite"] = "Lax"
        if COOKIE_SECURE:
            cookie[COOKIE_NAME]["secure"] = True
        cookie[COOKIE_NAME]["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
        self.send_header("Set-Cookie", cookie.output(header="").strip())

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

    def post_register(self) -> None:
        name = self.form.get("name", "")
        school = self.form.get("school", "")
        email_local = self.form.get("email_local", "")
        email = compose_edu_email(school, email_local, "/register")
        password = self.form.get("password", "")
        if len(name) < 2 or len(password) < 8:
            raise ValidationError("Isim, universite ve en az 8 karakter parola gerekli.", "/register")
        with db() as conn:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO users (name, email, password_hash, school, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (name, email, hash_password(password), school, now_iso()),
                )
            except sqlite3.IntegrityError:
                raise ValidationError("Bu email zaten kayitli.", "/register")
        self.login_and_redirect(cur.lastrowid, "Hesap olusturuldu.")

    def post_login(self) -> None:
        school = self.form.get("school", "")
        email_local = self.form.get("email_local", "")
        email = compose_edu_email(school, email_local, "/login")
        password = self.form.get("password", "")
        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user or not verify_password(password, user["password_hash"]):
            time.sleep(0.25)
            raise ValidationError("Email veya parola hatali.", "/login")
        self.login_and_redirect(user["id"], "Giris basarili.")

    def post_logout(self) -> None:
        if self.session:
            with db() as conn:
                conn.execute("DELETE FROM sessions WHERE id = ?", (self.session["id"],))
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.clear_session_cookie()
        self.end_headers()

    def get_home(self) -> None:
        if self.current_user:
            self.redirect("/dashboard")
            return
        self.render("StudyMate", home_page())

    def get_register(self) -> None:
        self.render("Kayit ol", auth_page("register"))

    def get_login(self) -> None:
        self.render("Giris yap", auth_page("login"))

    def get_dashboard(self) -> None:
        user = self.require_login()
        with db() as conn:
            open_posts = conn.execute(
                "SELECT COUNT(*) AS c FROM study_posts WHERE user_id = ? AND status = 'open'",
                (user["id"],),
            ).fetchone()["c"]
            incoming = conn.execute(
                "SELECT COUNT(*) AS c FROM study_requests WHERE receiver_id = ? AND status = 'pending'",
                (user["id"],),
            ).fetchone()["c"]
            matches = conn.execute(
                "SELECT COUNT(*) AS c FROM matches WHERE user1_id = ? OR user2_id = ?",
                (user["id"], user["id"]),
            ).fetchone()["c"]
            latest = conn.execute(
                """
                SELECT p.*, u.name, u.school
                FROM study_posts p
                JOIN users u ON u.id = p.user_id
                WHERE p.status = 'open' AND p.user_id != ?
                ORDER BY p.created_at DESC
                LIMIT 3
                """,
                (user["id"],),
            ).fetchall()
        self.render("Dashboard", dashboard_page(user, open_posts, incoming, matches, latest, self.csrf_input()))

    def get_profile(self) -> None:
        user = self.require_login()
        self.render("Profil", profile_page(user, self.csrf_input()))

    def post_profile(self) -> None:
        user = self.require_login()
        bio = self.form.get("bio", "")[:500]
        skills = self.form.get("skills", "")[:300]
        school = self.form.get("school", "")[:120]
        require_university(school, "/profile")
        phone = normalize_phone(self.form.get("phone", ""))
        with db() as conn:
            conn.execute(
                "UPDATE users SET school = ?, phone = ?, bio = ?, skills = ? WHERE id = ?",
                (school, phone, bio, skills, user["id"]),
            )
        self.redirect("/profile", "Profil guncellendi.", "success")

    def get_new_post(self) -> None:
        self.require_login()
        self.render("Ilan olustur", post_form_page(self.csrf_input()))

    def post_new_post(self) -> None:
        user = self.require_login()
        topic = self.form.get("topic", "")[:100]
        level = self.form.get("level", "")
        location = self.form.get("location", "")
        mode = self.form.get("mode", "")
        place = self.form.get("place_preference", "")
        start_time = self.form.get("start_time", "")
        end_time = self.form.get("end_time", "")
        description = self.form.get("description", "")[:700]
        if not topic or level not in LEVELS or location not in LOCATIONS or mode not in MODES or place not in PLACES:
            raise ValidationError("Ilan alanlarini kontrol et.", "/posts/new")
        validate_study_times(start_time, end_time)
        with db() as conn:
            conn.execute(
                """
                INSERT INTO study_posts
                (user_id, topic, level, location, mode, place_preference, start_time, end_time, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user["id"], topic, level, location, mode, place, start_time, end_time, description, now_iso()),
            )
        self.redirect("/posts", "Ilan yayinlandi.", "success")

    def get_posts(self) -> None:
        user = self.require_login()
        filters = {
            "location": self.query.get("location", ""),
            "topic": self.query.get("topic", ""),
            "level": self.query.get("level", ""),
            "mode": self.query.get("mode", ""),
        }
        clauses = ["p.status = 'open'", "p.user_id != ?"]
        params: list[Any] = [user["id"]]
        if filters["location"]:
            clauses.append("p.location = ?")
            params.append(filters["location"])
        if filters["level"]:
            clauses.append("p.level = ?")
            params.append(filters["level"])
        if filters["mode"]:
            clauses.append("p.mode = ?")
            params.append(filters["mode"])
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
        self.render("Ilanlar", posts_page(user, posts, filters, request_status, self.csrf_input()))

    def post_send_request(self) -> None:
        user = self.require_login()
        post_id = int(self.form.get("post_id", "0") or "0")
        message = self.form.get("message", "")[:240]
        with db() as conn:
            post = conn.execute("SELECT * FROM study_posts WHERE id = ? AND status = 'open'", (post_id,)).fetchone()
            if not post:
                raise ValidationError("Ilan bulunamadi.", "/posts")
            if post["user_id"] == user["id"]:
                raise ValidationError("Kendi ilanina istek gonderemezsin.", "/posts")
            one_hour_ago = (utcnow() - timedelta(hours=1)).isoformat(timespec="seconds")
            sent_count = conn.execute(
                "SELECT COUNT(*) AS c FROM study_requests WHERE sender_id = ? AND created_at >= ?",
                (user["id"], one_hour_ago),
            ).fetchone()["c"]
            if sent_count >= 10:
                raise ValidationError("Spam korumasi: bir saat icinde en fazla 10 istek gonderebilirsin.", "/posts")
            duplicate = conn.execute(
                """
                SELECT id FROM study_requests
                WHERE post_id = ? AND sender_id = ? AND status IN ('pending', 'accepted')
                """,
                (post_id, user["id"]),
            ).fetchone()
            if duplicate:
                raise ValidationError("Bu ilana zaten istek gonderdin.", "/posts")
            conn.execute(
                """
                INSERT INTO study_requests (post_id, sender_id, receiver_id, message, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """,
                (post_id, user["id"], post["user_id"], message, now_iso(), now_iso()),
            )
        self.redirect("/posts", "Istek gonderildi.", "success")

    def get_requests(self) -> None:
        user = self.require_login()
        with db() as conn:
            incoming = conn.execute(
                """
                SELECT r.*, p.topic, p.location, p.start_time, p.end_time, u.name AS sender_name, u.school, u.skills
                FROM study_requests r
                JOIN study_posts p ON p.id = r.post_id
                JOIN users u ON u.id = r.sender_id
                WHERE r.receiver_id = ?
                ORDER BY r.created_at DESC
                """,
                (user["id"],),
            ).fetchall()
            outgoing = conn.execute(
                """
                SELECT r.*, p.topic, p.location, p.start_time, p.end_time, u.name AS receiver_name
                FROM study_requests r
                JOIN study_posts p ON p.id = r.post_id
                JOIN users u ON u.id = r.receiver_id
                WHERE r.sender_id = ?
                ORDER BY r.created_at DESC
                """,
                (user["id"],),
            ).fetchall()
        self.render("Istekler", requests_page(incoming, outgoing, self.csrf_input()))

    def post_respond_request(self) -> None:
        user = self.require_login()
        request_id = int(self.form.get("request_id", "0") or "0")
        action = self.form.get("action", "")
        if action not in {"accepted", "rejected"}:
            raise ValidationError("Gecersiz istek aksiyonu.", "/requests")
        with db() as conn:
            req = conn.execute("SELECT * FROM study_requests WHERE id = ?", (request_id,)).fetchone()
            if not req or req["receiver_id"] != user["id"] or req["status"] != "pending":
                raise ValidationError("Istek bulunamadi veya zaten yanitlanmis.", "/requests")
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
        msg = "Eslesme olustu." if action == "accepted" else "Istek reddedildi."
        self.redirect("/requests", msg, "success")

    def get_matches(self) -> None:
        user = self.require_login()
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
                WHERE m.user1_id = ? OR m.user2_id = ?
                ORDER BY m.created_at DESC
                """,
                (user["id"], user["id"], user["id"], user["id"], user["id"]),
            ).fetchall()
        self.render("Eslesmeler", matches_page(user, matches, self.csrf_input()))

    def post_report(self) -> None:
        user = self.require_login()
        reported_user_id = int(self.form.get("reported_user_id", "0") or "0")
        reason = self.form.get("reason", "")[:500]
        if reported_user_id == user["id"] or len(reason) < 5:
            raise ValidationError("Rapor nedeni en az 5 karakter olmali.", "/matches")
        with db() as conn:
            exists = conn.execute("SELECT id FROM users WHERE id = ?", (reported_user_id,)).fetchone()
            if not exists:
                raise ValidationError("Kullanici bulunamadi.", "/matches")
            conn.execute(
                "INSERT INTO reports (reporter_id, reported_user_id, reason, created_at) VALUES (?, ?, ?, ?)",
                (user["id"], reported_user_id, reason, now_iso()),
            )
        self.redirect("/matches", "Rapor kaydedildi.", "success")

    def get_security(self) -> None:
        self.render("Guvenlik", security_page())


class AuthRequired(Exception):
    pass


class CsrfError(Exception):
    pass


class ValidationError(Exception):
    def __init__(self, message: str, redirect_to: str) -> None:
        super().__init__(message)
        self.redirect_to = redirect_to


def layout(title: str, content: str, user: sqlite3.Row | None, flash: str) -> str:
    nav = (
        """
        <a href="/dashboard">Panel</a>
        <a href="/posts">Ilanlar</a>
        <a href="/requests">Istekler</a>
        <a href="/matches">Eslesmeler</a>
        <a href="/profile">Profil</a>
        """
        if user
        else """
        <a href="/security">Guvenlik</a>
        <a class="nav-pill" href="/login">Giris</a>
        <a class="button small" href="/register">Basla</a>
        """
    )
    user_chip = f'<span class="user-chip">{escape(user["name"])}</span>' if user else ""
    return f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)} | StudyMate</title>
  <link rel="stylesheet" href="/static/styles.css">
  <script defer src="/static/app.js"></script>
</head>
<body>
  <a class="skip-link" href="#content">Icerige gec</a>
  <header class="topbar">
    <a class="brand" href="/" aria-label="StudyMate ana sayfa"><span class="brand-mark">SM</span><span>StudyMate</span></a>
    <nav aria-label="Ana navigasyon">{nav}</nav>
    {user_chip}
  </header>
  <main id="content">
    {flash}
    {content}
  </main>
  <footer class="site-footer">
    <span>StudyMate MVP</span>
    <a href="/security">Guvenlik ilkeleri</a>
  </footer>
</body>
</html>"""


def home_page() -> str:
    return """
    <section class="hero">
      <div class="hero-copy">
        <p class="eyebrow">Universite odakli calisma agi</p>
        <h1>Konu, seviye ve semte gore calisma arkadasi bul.</h1>
        <p class="lead">StudyMate; edu mail, public bulusma onerisi ve istek onayi ile ogrencileri daha kontrollu bir calisma akisinda eslestirir.</p>
        <div class="actions">
          <a class="button" href="/register">Hemen basla</a>
          <a class="ghost" href="/login">Demo hesapla gir</a>
        </div>
        <div class="trust-row" aria-label="Guven sinyalleri">
          <span>Edu domain kontrolu</span>
          <span>CSRF korumasi</span>
          <span>Telefon gizliligi</span>
        </div>
      </div>
      <div class="hero-panel">
        <div class="match-card preview-card">
          <div class="preview-head">
            <div>
              <span class="badge">AI Match Score 87%</span>
              <h3>Ece ile Backend API</h3>
            </div>
            <span class="avatar">ED</span>
          </div>
          <p>Besiktas civarinda Flask endpoint tasarimi calisacak bir partner ariyor.</p>
          <div class="meta">
            <span>Intermediate</span>
            <span>Kutuphane</span>
            <span>Bugun 18:00</span>
          </div>
          <div class="safe-box">
            Kabulden once telefon ve tam adres gizli kalir. Eslesme olunca public yer onerisi acilir.
          </div>
        </div>
      </div>
    </section>
    <section class="stats landing-stats">
      <article><strong>3 adim</strong><span>Ilan ac, istek al, esles</span></article>
      <article><strong>10/saat</strong><span>Spam limiti</span></article>
      <article><strong>edu</strong><span>Okul domaini zorunlu</span></article>
    </section>
    <section class="features">
      <article><span class="feature-icon">01</span><h3>Hedef odakli</h3><p>Swipe yerine konu, seviye, zaman ve semt bazli calisma ilanlari var.</p></article>
      <article><span class="feature-icon">02</span><h3>Kontrollu</h3><p>Istek kabul edilmeden telefon gosterilmez; ilk bulusma icin public yer onerilir.</p></article>
      <article><span class="feature-icon">03</span><h3>Yayina hazir MVP</h3><p>Kayit, giris, ilan, istek, eslesme, rapor ve temel guvenlik akislarini kapsar.</p></article>
    </section>
    """


def auth_page(mode: str) -> str:
    is_register = mode == "register"
    action = "/register" if is_register else "/login"
    title = "Hesap olustur" if is_register else "Giris yap"
    extra = (
        """
        <label>Isim
          <input name="name" required minlength="2" autocomplete="name">
        </label>
        """
        if is_register
        else ""
    )
    default_school = "Bahcesehir University" if "Bahcesehir University" in UNIVERSITY_BY_NAME else (UNIVERSITIES[0]["name"] if UNIVERSITIES else "")
    default_domain = UNIVERSITY_BY_NAME.get(default_school, {}).get("domain", "edu.tr")
    helper = (
        '<p class="form-intro">Demo hesap: ahmet @bogazici.edu.tr / Ahmet2026! veya ece @itu.edu.tr / Ece2026!</p>'
        if not is_register
        else '<p class="form-intro">Universiteni sec, sadece @ oncesindeki ogrenci mail adini yaz. Domain okuldan otomatik gelir.</p>'
    )
    alternate = (
        '<p class="auth-switch">Hesabin var mi? <a href="/login">Giris yap</a></p>'
        if is_register
        else '<p class="auth-switch">Hesabin yok mu? <a href="/register">Kayit ol</a></p>'
    )
    password_autocomplete = "new-password" if is_register else "current-password"
    return f"""
    <section class="form-wrap narrow">
      <h1>{title}</h1>
      {helper}
      <form method="post" action="{action}" class="stack">
        {extra}
        <label>Universite
          <select name="school" class="js-school-select" data-domain-target="email-domain" required>
            {school_options(default_school)}
          </select>
        </label>
        <label>Edu mail
          <span class="email-composer">
            <input name="email_local" required autocomplete="username" placeholder="ogrenci.no veya ad.soyad" pattern="[A-Za-z0-9._%+\\-]{{1,64}}">
            <span class="email-domain">@<span id="email-domain">{escape(default_domain)}</span></span>
          </span>
        </label>
        <label>Parola
          <input type="password" name="password" required minlength="8" autocomplete="{password_autocomplete}">
        </label>
        <button class="button" type="submit">{title}</button>
      </form>
      {alternate}
    </section>
    """


def dashboard_page(user: sqlite3.Row, open_posts: int, incoming: int, matches: int, latest: list[sqlite3.Row], csrf: str) -> str:
    cards = "".join(compact_post_card(row) for row in latest) or '<p class="empty">Sana uygun yeni ilan yok.</p>'
    return f"""
    <section class="page-head">
      <div>
        <p class="eyebrow">Merhaba {escape(user["name"])}</p>
        <h1>Bugunku calisma panelin</h1>
      </div>
      <form method="post" action="/logout">{csrf}<button class="ghost danger" type="submit">Cikis</button></form>
    </section>
    <section class="stats">
      <article><strong>{open_posts}</strong><span>Acik ilanin</span></article>
      <article><strong>{incoming}</strong><span>Bekleyen istek</span></article>
      <article><strong>{matches}</strong><span>Aktif eslesme</span></article>
    </section>
    <section class="quick-actions">
      <a class="button" href="/posts/new">Calisma ilani olustur</a>
      <a class="ghost" href="/posts">Yakindaki ilanlari gor</a>
    </section>
    <section>
      <div class="section-title">
        <div>
          <p class="eyebrow">Kesfet</p>
          <h2>Son ilanlar</h2>
        </div>
        <a class="text-link" href="/posts">Tumunu gor</a>
      </div>
      <div class="grid">{cards}</div>
    </section>
    """


def profile_page(user: sqlite3.Row, csrf: str) -> str:
    return f"""
    <section class="form-wrap">
      <h1>Profil</h1>
      <p class="form-intro">Eslesme kalitesini artirmak icin calistigin teknolojileri ve kisa hedefini ekle.</p>
      <form method="post" action="/profile" class="stack">
        {csrf}
        <label>Universite
          <select name="school" required>
            {school_options(user["school"])}
          </select>
        </label>
        <label>Telefon
          <input name="phone" value="{escape(user["phone"])}" inputmode="tel" autocomplete="tel" placeholder="+90 555 123 45 67">
        </label>
        <p class="hint">Telefon numaran sadece eslesme kabul edildikten sonra karsi tarafa gosterilir.</p>
        <label>Ilgi alanlari
          <input name="skills" value="{escape(user["skills"])}" maxlength="300" placeholder="Python, Flask, SQL">
        </label>
        <label>Bio
          <textarea name="bio" rows="5" maxlength="500" placeholder="Ne calisiyorsun?">{escape(user["bio"])}</textarea>
        </label>
        <button class="button" type="submit">Kaydet</button>
      </form>
    </section>
    """


def post_form_page(csrf: str) -> str:
    start = datetime_local()
    end = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
    return f"""
    <section class="form-wrap">
      <h1>Calisma ilani olustur</h1>
      <p class="form-intro">Konu ve zaman bilgisini net yaz; sistem benzer ilgi alanlarini yakalayip match skorunu hesaplar.</p>
      <form method="post" action="/posts/new" class="stack">
        {csrf}
        <label>Konu
          <input name="topic" required maxlength="100" placeholder="Python Flask">
        </label>
        <div class="two-col">
          <label>Seviye
            <select name="level">{option_tags(LEVELS)}</select>
          </label>
          <label>Konum
            <select name="location">{option_tags(LOCATIONS)}</select>
          </label>
        </div>
        <div class="two-col">
          <label>Calisma tipi
            <select name="mode">{option_tags(MODES)}</select>
          </label>
          <label>Yer tercihi
            <select name="place_preference">{option_tags(PLACES)}</select>
          </label>
        </div>
        <div class="two-col">
          <label>Baslangic
            <input type="datetime-local" name="start_time" value="{start}" required>
          </label>
          <label>Bitis
            <input type="datetime-local" name="end_time" value="{end}" required>
          </label>
        </div>
        <label>Aciklama
          <textarea name="description" rows="5" maxlength="700" placeholder="Flask ogreniyorum, beraber mini API yapmak istiyorum."></textarea>
        </label>
        <button class="button" type="submit">Yayinla</button>
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
        post_cards = '<p class="empty">Filtrelere uyan ilan yok. Yeni ilan acarak talep olusturabilirsin.</p>'
    return f"""
    <section class="page-head">
      <div>
        <p class="eyebrow">Semt bazli eslesme</p>
        <h1>Yakindaki ilanlar</h1>
      </div>
      <a class="button" href="/posts/new">Yeni ilan</a>
    </section>
    <form method="get" action="/posts" class="filters">
      <input name="topic" value="{escape(filters["topic"])}" placeholder="Konu ara">
      <select name="location"><option value="">Tum konumlar</option>{option_tags(LOCATIONS, filters["location"])}</select>
      <select name="level"><option value="">Tum seviyeler</option>{option_tags(LEVELS, filters["level"])}</select>
      <select name="mode"><option value="">Tum tipler</option>{option_tags(MODES, filters["mode"])}</select>
      <button class="ghost" type="submit">Filtrele</button>
    </form>
    <section class="grid">{post_cards}</section>
    """


def match_score(user: sqlite3.Row, post: sqlite3.Row) -> tuple[int, str]:
    user_words = slug_words(f'{user["skills"]} {user["bio"]}')
    post_words = slug_words(f'{post["topic"]} {post["description"]} {post["skills"]}')
    overlap = user_words & post_words
    base = 45
    score = min(96, base + len(overlap) * 12)
    if overlap:
        reason = "Ortak anahtar kelimeler: " + ", ".join(sorted(overlap)[:4])
    else:
        reason = "Konu ve zaman bilgisi uzerinden temel uygunluk."
    return score, reason


def post_card(user: sqlite3.Row, post: sqlite3.Row, status: str | None, csrf: str) -> str:
    score, reason = match_score(user, post)
    request_area = (
        f'<span class="status">Istek durumu: {escape(status)}</span>'
        if status
        else f"""
        <form method="post" action="/requests/send" class="inline-form">
          {csrf}
          <input type="hidden" name="post_id" value="{post["id"]}">
          <input name="message" maxlength="240" placeholder="Kisa mesaj (opsiyonel)">
          <button class="button small" type="submit">Istek gonder</button>
        </form>
        """
    )
    return f"""
    <article class="card">
      <div class="card-top">
        <div>
          <p class="card-kicker">{escape(post["name"])} - {escape(post["school"])}</p>
          <h3>{escape(post["topic"])}</h3>
        </div>
        <span class="badge">AI {score}%</span>
      </div>
      <p><strong>{escape(post["level"])}</strong> seviye icin calisma daveti.</p>
      <p>{escape(post["description"])}</p>
      <div class="meta">
        <span>{escape(post["location"])}</span>
        <span>{escape(post["mode"])}</span>
        <span>{escape(post["place_preference"])}</span>
        <span>{escape(display_time_range(post["start_time"], post["end_time"]))}</span>
      </div>
      <p class="hint">{escape(reason)}</p>
      {request_area}
    </article>
    """


def compact_post_card(post: sqlite3.Row) -> str:
    return f"""
    <article class="card compact">
      <p class="card-kicker">{escape(post["name"])} - {escape(post["school"])}</p>
      <h3>{escape(post["topic"])}</h3>
      <p>{escape(post["location"])} / {escape(display_time_range(post["start_time"], post["end_time"]))}</p>
    </article>
    """


def requests_page(incoming: list[sqlite3.Row], outgoing: list[sqlite3.Row], csrf: str) -> str:
    incoming_html = "".join(incoming_request_card(row, csrf) for row in incoming) or '<p class="empty">Gelen istek yok.</p>'
    outgoing_html = "".join(
        f"""
        <article class="card compact">
          <h3>{escape(row["receiver_name"])}</h3>
          <p>{escape(row["topic"])} - {escape(row["location"])}</p>
          <p class="muted">{escape(display_time_range(row["start_time"], row["end_time"]))}</p>
          <span class="status {escape(row["status"])}">{escape(row["status"])}</span>
        </article>
        """
        for row in outgoing
    ) or '<p class="empty">Gonderdigin istek yok.</p>'
    return f"""
    <section class="page-head"><h1>Istekler</h1></section>
    <section>
      <h2>Gelen istekler</h2>
      <div class="grid">{incoming_html}</div>
    </section>
    <section>
      <h2>Gonderilen istekler</h2>
      <div class="grid">{outgoing_html}</div>
    </section>
    """


def incoming_request_card(row: sqlite3.Row, csrf: str) -> str:
    controls = ""
    if row["status"] == "pending":
        controls = f"""
        <form method="post" action="/requests/respond" class="row-actions">
          {csrf}
          <input type="hidden" name="request_id" value="{row["id"]}">
          <button class="button small" name="action" value="accepted" type="submit">Kabul et</button>
          <button class="ghost danger small" name="action" value="rejected" type="submit">Reddet</button>
        </form>
        """
    else:
        controls = f'<span class="status {escape(row["status"])}">{escape(row["status"])}</span>'
    return f"""
    <article class="card">
      <h3>{escape(row["sender_name"])}</h3>
      <p class="muted">{escape(row["school"])} - {escape(row["skills"])}</p>
      <p>{escape(row["topic"])} ilani icin katilmak istiyor.</p>
      <p class="hint">{escape(row["message"])}</p>
      <div class="meta"><span>{escape(row["location"])}</span><span>{escape(display_time_range(row["start_time"], row["end_time"]))}</span></div>
      {controls}
    </article>
    """


def matches_page(user: sqlite3.Row, matches: list[sqlite3.Row], csrf: str) -> str:
    cards = "".join(match_card(user, row, csrf) for row in matches) or '<p class="empty">Henuz eslesme yok.</p>'
    return f"""
    <section class="page-head"><h1>Eslesmeler</h1></section>
    <div class="safety-note">
      Tam adres paylasma. Ilk bulusma icin kalabalik ve public alan sec. Sorunlu davranisi raporla.
    </div>
    <section class="grid">{cards}</section>
    """


def match_card(user: sqlite3.Row, row: sqlite3.Row, csrf: str) -> str:
    suggestion = PUBLIC_PLACES.get(row["location"], "Kalabalik ve public bir alan")
    phone = row["other_phone"] or "Telefon girilmemis"
    return f"""
    <article class="card">
      <span class="badge">Eslesme tamam</span>
      <h3>{escape(row["other_name"])}</h3>
      <p><strong>{escape(row["topic"])}</strong> - {escape(row["location"])}</p>
      <div class="meta"><span>{escape(row["mode"])}</span><span>{escape(row["place_preference"])}</span><span>{escape(display_time_range(row["start_time"], row["end_time"]))}</span></div>
      <p class="contact-line"><strong>Telefon:</strong> {escape(phone)}</p>
      <p class="hint">Onerilen guvenli yer: {escape(suggestion)}</p>
      <details>
        <summary>Raporla</summary>
        <form method="post" action="/reports" class="stack mini">
          {csrf}
          <input type="hidden" name="reported_user_id" value="{row["other_id"]}">
          <textarea name="reason" rows="3" required placeholder="Kisa neden"></textarea>
          <button class="ghost danger small" type="submit">Rapor gonder</button>
        </form>
      </details>
    </article>
    """


def security_page() -> str:
    return """
    <section class="form-wrap">
      <h1>Guvenlik ve gizlilik</h1>
      <ul class="checklist">
        <li>Parolalar PBKDF2-SHA256, kullaniciya ozel salt ve 310.000 iterasyon ile hashlenir.</li>
        <li>Kullanici okulunu Turkiye universite listesinden secer; email domain'i okul domain'iyle zorunlu eslesir.</li>
        <li>Session tokenlari cookie'de random token olarak durur; veritabaninda sadece SHA-256 hash saklanir.</li>
        <li>POST formlarinda CSRF token kontrolu vardir.</li>
        <li>Tam adres tutulmaz; sadece semt veya Online secenegi kullanilir.</li>
        <li>Telefon numarasi ilan ve isteklerde gizlidir; sadece kabul edilen eslesmelerde iki tarafa acilir.</li>
        <li>Istek gonderme saatlik limite tabidir ve ayni ilana tekrar istek engellenir.</li>
        <li>Eslesme sonrasi public place onerisi ve raporlama akisi vardir.</li>
      </ul>
    </section>
    """


def page_not_found() -> str:
    return '<section class="form-wrap"><h1>404</h1><p>Bu sayfa yok.</p><a class="button" href="/">Ana sayfa</a></section>'


def error_page(exc: Exception) -> str:
    return f"""
    <section class="form-wrap">
      <h1>Beklenmeyen hata</h1>
      <p class="muted">{escape(exc)}</p>
      <a class="button" href="/dashboard">Panele don</a>
    </section>
    """


def main() -> None:
    init_db()
    seed_demo()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), StudyMateApp)
    print(f"StudyMate running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
