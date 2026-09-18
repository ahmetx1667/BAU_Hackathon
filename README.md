# StudyMate

**1st place — BAU Hackathon '26, Bahçeşehir University.**

StudyMate pairs university students with a study partner by subject, level, time
and district. It was built for the hackathon brief *solve something that annoys
you in daily life*: finding someone to actually study with is a coordination
problem, and the existing answer is a group chat where nobody replies.

The backend runs on the **Python standard library alone** — no Flask, no Django,
no ORM, no third-party packages at all. HTTP comes from `http.server`, storage
from `sqlite3`, and the password and session handling from `hashlib`, `hmac` and
`secrets`. The only optional dependency is an LLM API key, and the app works
without it.

## Running it

Python 3.11 or newer. There is nothing to install.

```bash
python run.py
```

Then open <http://127.0.0.1:8000>.

The first run creates `instance/studymate.sqlite3` and `instance/secret.key`, and
seeds three demo accounts with open study sessions:

| Email | Password |
|---|---|
| `ahmet@bogazici.edu.tr` | `Ahmet2026!` |
| `ece@itu.edu.tr` | `Ece2026!` |
| `mert@marmara.edu.tr` | `Mert2026!` |

Sign in by picking the university from the dropdown and typing only the part of
the address before the `@`. Neither `instance/` file belongs in version control.

## How it works

A student registers with a **university email address** — they choose their
university from a dataset of Turkish institutions and enter only the local part,
so the domain is never free text. That is what makes it reasonable to believe the
person on the other side is a real student.

They then post a **study session** (subject, level, district, in-person or
online, a time window) or browse other people's. Each session is scored for how
well it fits the viewer, and the score is explained in one sentence.

Someone interested sends a **request**. Nothing is shared at this point. Only
when the session's owner **accepts** does the pair become a match, and only then
do the two phone numbers become visible to each other — alongside a suggested
public, busy place to meet. Either side can report the other from the match card.

### Privacy and safety decisions

These were deliberate, and they are the part of the project worth reading:

- **Contact details are released on mutual consent, never before.** A phone
  number only appears after both sides accept. Until then a session shows a
  district, never an address.
- **First meetings are steered somewhere public.** Every match carries a
  suggestion — a district library, a busy cafe — because the software should not
  be neutral about where two strangers meet for the first time.
- **Only a district is ever stored**, not a location.
- **Passwords are PBKDF2-HMAC-SHA256** with a random per-user salt, at 310,000
  iterations, verified in constant time. The iteration count is stored alongside
  each hash, so it can be raised later without invalidating existing passwords.
- **Session tokens are stored hashed**, so a database leak cannot be replayed as
  a live login cookie.
- **CSRF tokens** are bound to the session and checked on every state-changing
  POST, also in constant time.
- **Abuse limits**: 10 study requests per account per hour, a 10-minute lockout
  after 10 failed sign-ins from one address, and a 64 KB cap on request bodies.
- **Flash messages are signed.** They travel in the query string across a
  redirect, so without a signature anyone could send a link that renders their
  own text on our page — escaped, so not XSS, but a convincing phishing page on
  a domain the reader already trusts.
- **The demo accounts do not seed on a public bind.** Their passwords are in this
  README, so they are only created when the app is bound to loopback.

### Match scoring

`match_score()` asks an LLM (DeepSeek) to rate the fit and explain it, with an
in-memory cache keyed on `(student, session)` so a page of results does not
become a page of API calls.

With no API key configured — and whenever the API call fails or times out — it
falls back to **keyword overlap** between the student's interests and the
session's text. This is not a stub. It is what runs on a fresh clone, and it is
what kept the demo alive when the network did not.

## Layout

```
run.py                     entry point
studymate/
  config.py                paths, environment, tunable limits
  constants.py             districts, levels, modes, labels, stop words
  errors.py                the exceptions the dispatcher turns into responses
  formatting.py            escaping, labels, dates, input normalisation
  security.py              password hashing, token hashing, app secret
  universities.py          the university dataset and the .edu email rule
  database.py              schema, migrations, demo seed
  matching.py              match scoring, LLM client and keyword fallback
  server.py                HTTP dispatch, sessions, CSRF, route handlers
  views/
    layout.py              the page shell
    pages.py               one function per route
    cards.py               repeated card components
data/turkish_universities.json
static/                    stylesheet, script, logo
```

Language note: the interface is English, but place and institution names stay in
Turkish — `Beşiktaş` and `Bahçeşehir Üniversitesi` are names, not strings to be
translated. The keyword stop-word list covers both languages, because students
write their posts in either.

## Configuration

Copy `.env.example` to `.env` and edit it. Real environment variables always take
precedence over the file, so a shell, systemd unit or hosting panel can override
anything.

| Variable | Default | What it does |
|---|---|---|
| `HOST` | `127.0.0.1` | Interface to bind. Use `0.0.0.0` only behind a reverse proxy. |
| `PORT` | `8000` | HTTP port. |
| `STUDYMATE_SECRET_KEY` | generated | Signs flash messages. Set explicitly in production. |
| `STUDYMATE_DB_PATH` | `instance/studymate.sqlite3` | SQLite file location. |
| `STUDYMATE_SECRET_PATH` | `instance/secret.key` | Where the generated secret is kept. |
| `STUDYMATE_COOKIE_SECURE` | `0` | Set to `1` when served over HTTPS. |
| `STUDYMATE_SEED_DEMO` | loopback only | Seeds the demo accounts. Never enable this publicly. |
| `DEEPSEEK_API_KEY` | empty | Enables LLM scoring; falls back to keywords when unset. |

Generate a secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Status

This is a hackathon MVP, and it is honest about what that means. It runs one
process against a SQLite file, rate limiting lives in memory and resets on
restart, and there is no email verification beyond requiring a university domain
— a student could register with a classmate's address. It has not been through a
security review. Do not deploy it to a public address as it stands.

## Team

Built in 24 hours at BAU Hackathon '26 by a team of four.

| | |
|---|---|
| Ahmet Aydın | [@ahmetx1667](https://github.com/ahmetx1667) |
| Arda Karaböcek | [@ardakarabck](https://github.com/ardakarabck) |

<!-- Add your two other teammates here with their GitHub handles, and note who
     owned which part — it matters to anyone reading this as a portfolio piece. -->

## Data

The university list is derived from public records of Turkish higher-education
institutions.

## Licence

No licence has been declared yet. Until one is added, default copyright applies
and nobody else may reuse this code.
