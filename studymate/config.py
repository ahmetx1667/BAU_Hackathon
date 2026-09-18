"""Runtime configuration: paths, environment loading and tunable settings.

Everything here is resolved once, at import time, from the environment. A `.env`
file at the project root is read first, but real environment variables always win
over it, so a shell, systemd unit or hosting panel can override any value.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# The project root is the directory containing this package, not the package itself.
ROOT = Path(__file__).resolve().parents[1]


def load_env_file(path: Path = ROOT / ".env") -> None:
    """Load KEY=VALUE pairs from a .env file without any third-party dependency.

    Existing environment variables are never overwritten, so anything already set
    in the shell takes precedence over the file.
    """
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


def runtime_path(env_name: str, default: Path) -> Path:
    """Resolve a path that may be overridden by an environment variable.

    A relative override is interpreted against the project root, so a value like
    `var/studymate.sqlite3` lands somewhere predictable no matter where the
    process was started from.
    """
    configured = os.environ.get(env_name)
    if not configured:
        return default
    path = Path(configured).expanduser()
    return path if path.is_absolute() else ROOT / path


# ---- Filesystem layout -----------------------------------------------------

INSTANCE_DIR = ROOT / "instance"
STATIC_DIR = ROOT / "static"
UNIVERSITIES_PATH = ROOT / "data" / "turkish_universities.json"

DB_PATH = runtime_path("STUDYMATE_DB_PATH", INSTANCE_DIR / "studymate.sqlite3")
SECRET_PATH = runtime_path("STUDYMATE_SECRET_PATH", INSTANCE_DIR / "secret.key")

# ---- Server ----------------------------------------------------------------

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))

# ---- Sessions and authentication -------------------------------------------

COOKIE_NAME = "studymate_session"
SESSION_DAYS = 7
PBKDF2_ITERATIONS = 310_000

# Only the local part of the address is typed by the user; the domain comes from
# the selected university, so this pattern deliberately excludes "@".
EMAIL_LOCAL_RE = re.compile(r"^[a-z0-9._%+-]{1,64}$")

# Set this whenever the app is served over HTTPS so the session cookie is only
# ever sent on an encrypted connection.
COOKIE_SECURE = os.environ.get("STUDYMATE_COOKIE_SECURE", "").lower() in {"1", "true", "yes", "on"}

# ---- Abuse limits ----------------------------------------------------------

MAX_REQUESTS_PER_HOUR = 10       # study requests one account may send per hour
MAX_FAILED_LOGINS = 10           # failed attempts from one IP before a lockout
LOGIN_LOCKOUT_SECONDS = 600      # how long that lockout lasts

# Longest form submission accepted. Every form on the site fits in a few KB; the
# cap exists so a request that merely *claims* a huge Content-Length cannot make
# the server allocate it.
MAX_BODY_BYTES = 64 * 1024

# Distinct client addresses tracked for failed logins. Past this the oldest
# entries are dropped, so the table cannot grow without bound.
MAX_TRACKED_CLIENTS = 10_000

# ---- Demo data -------------------------------------------------------------
#
# The seeded accounts have passwords published in the README, so they must never
# appear on a public deployment. Default: on when bound to loopback (a developer
# running it locally), off otherwise. STUDYMATE_SEED_DEMO overrides either way.

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_seed_override = os.environ.get("STUDYMATE_SEED_DEMO", "").lower()
if _seed_override in {"1", "true", "yes", "on"}:
    SEED_DEMO = True
elif _seed_override in {"0", "false", "no", "off"}:
    SEED_DEMO = False
else:
    SEED_DEMO = HOST in _LOOPBACK

# ---- Match scoring ---------------------------------------------------------

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_TIMEOUT_SECONDS = 8
