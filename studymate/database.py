"""SQLite schema, connection helper, migrations and the demo seed."""

from __future__ import annotations

import sqlite3
from datetime import timedelta

from .config import DB_PATH
from .formatting import current_datetime_local, datetime_local, localnow, now_iso
from .security import hash_password

SCHEMA = """
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
CREATE INDEX IF NOT EXISTS idx_posts_active ON study_posts(status, end_time);
CREATE INDEX IF NOT EXISTS idx_requests_receiver ON study_requests(receiver_id, status);
CREATE INDEX IF NOT EXISTS idx_requests_sender ON study_requests(sender_id, status);
"""

# The interface moved from Turkish to English, and these values are stored in the
# database rather than looked up, so old rows have to be rewritten once.
LEGACY_VALUE_MAP = {
    "mode": {"Yuz yuze": "In person"},
    "place_preference": {"Kafe": "Cafe", "Kutuphane": "Library", "Kampus": "Campus"},
}


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Off by default in SQLite; without it the ON DELETE CASCADE rules above do nothing.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate_legacy_values(conn: sqlite3.Connection) -> None:
    """Rewrite Turkish enum values left over from the original version."""
    for column, mapping in LEGACY_VALUE_MAP.items():
        for old, new in mapping.items():
            conn.execute(
                f"UPDATE study_posts SET {column} = ? WHERE {column} = ?",  # noqa: S608 - column names are literals above
                (new, old),
            )


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)

        # `phone` was added after the first release.
        user_columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "phone" not in user_columns:
            conn.execute("ALTER TABLE users ADD COLUMN phone TEXT NOT NULL DEFAULT ''")

        migrate_legacy_values(conn)

        # An online session has no district or venue; older rows predate that rule.
        conn.execute(
            "UPDATE study_posts SET location = 'Online', place_preference = 'Online' WHERE mode = 'Online'"
        )


def expire_past_posts() -> None:
    """Close out sessions whose end time has passed.

    Called on every request rather than on a timer: there is no scheduler in a
    single-process standard-library app, and the query is indexed and cheap.
    """
    with db() as conn:
        conn.execute(
            "UPDATE study_posts SET status = 'expired' WHERE status = 'open' AND end_time <= ?",
            (current_datetime_local(),),
        )


# The school names here must match `data/turkish_universities.json` exactly —
# sign-in resolves the email domain by looking the name up in that dataset.
DEMO_USERS = [
    (
        "Ahmet Kaya",
        "ahmet@bogazici.edu.tr",
        "Ahmet2026!",
        "Boğaziçi University",
        "+90 555 100 10 10",
        "Studying physics and mathematics, mostly interested in mechanics.",
        "Physics, Mathematics, Linear Algebra",
    ),
    (
        "Ece Demir",
        "ece@itu.edu.tr",
        "Ece2026!",
        "Istanbul Technical University",
        "+90 555 200 20 20",
        "Working on organic chemistry and biology.",
        "Chemistry, Biology, Organic Chemistry",
    ),
    (
        "Mert Yılmaz",
        "mert@marmara.edu.tr",
        "Mert2026!",
        "Marmara University",
        "+90 555 300 30 30",
        "Focusing on calculus and differential equations.",
        "Mathematics, Calculus, Statistics",
    ),
]


def seed_demo() -> None:
    """Populate three accounts and three open sessions on an empty database.

    Skipped entirely once any user exists, so it never touches real data.
    """
    with db() as conn:
        if conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]:
            return

        for name, email, password, school, phone, bio, skills in DEMO_USERS:
            conn.execute(
                """
                INSERT INTO users (name, email, password_hash, school, phone, bio, skills, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (name, email, hash_password(password), school, phone, bio, skills, now_iso()),
            )

        ids = {
            email: conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()["id"]
            for _, email, *_ in DEMO_USERS
        }
        start = datetime_local()
        end = (localnow() + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")

        posts = [
            (
                ids["ahmet@bogazici.edu.tr"], "Classical Mechanics", "Beginner",
                "Besiktas", "In person", "Library", start, end,
                "Going through Newtonian mechanics and conservation of energy together.",
            ),
            (
                ids["ece@itu.edu.tr"], "Organic Chemistry", "Intermediate",
                "Besiktas", "In person", "Cafe", start, end,
                "Working through reaction mechanisms and stereochemistry.",
            ),
            (
                ids["mert@marmara.edu.tr"], "Calculus", "Intermediate",
                "Online", "Online", "Online", start, end,
                "Practising integration and derivative applications.",
            ),
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
