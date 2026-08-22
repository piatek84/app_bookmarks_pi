# app_bookmarks_pi

Single-process Python rewrite of `app_bookmarks`, meant to run permanently on
a Raspberry Pi: one FastAPI service serves both the API and the HTML pages
(server-rendered with Jinja2, no JS, no separate frontend build), backed by
one SQLite file. No Kafka, no second service -- everything the original
project split across `frontend` / `backend-bookmarks` / `backend-telegram-notifier`
lives here in a single app.

Login is the same passwordless flow as the original project: you request a
code, it's sent to your Telegram chat by the same bot, you enter it back to
get a session cookie.

## Layout

```
app_bookmarks_pi/
├── bookmarks_pi/
│   ├── main.py        FastAPI routes
│   ├── db.py           sqlite3 schema + queries (no ORM)
│   ├── telegram.py     Telegram Bot API sendMessage wrapper
│   ├── config.py        env-based settings
│   ├── templates/       Jinja2 HTML pages
│   └── static/          styles.css
├── scripts/seed_user.py  creates a user row (no signup endpoint, same as the original)
├── deploy/bookmarks-pi.service  example systemd unit for the Pi
├── data/                  SQLite file lives here (gitignored)
└── tests/                 pytest, db + telegram layers
```

## Data model (SQLite)

- **`users`** -- `username` (unique), `telegram_chat_id`, `created_at`. No
  signup endpoint; create rows with `scripts/seed_user.py`.
- **`login_codes`** -- `username`, `code`, `used`, `expires_at`,
  `created_at`. A code is single-use and checked against `expires_at` on
  verify; nothing prunes old rows automatically (unlike the original's Mongo
  TTL index) since this is a tiny personal DB.
- **`bookmarks`** -- `owner_username`, `category`, `name`, `url`,
  `created_at`. Indexed on `(owner_username, category)`.
- **`birthdays`** -- `owner_username`, `title`, `month`, `day` (no year --
  recurs every year), `created_at`.
- **`vacations`** -- `owner_username`, `title`, `start_date`, `end_date`
  (both `YYYY-MM-DD`).
- **`work_shifts`** -- one row per `owner_username`, `start_date`. The
  calendar computes a 6-days-on/3-days-off rest cycle forward from that date
  (`bookmarks_pi/calendar_service.py`); there's no signup endpoint for it
  either, it's set from the "Work shift" form on the bookmarks page.

All three are scoped per `owner_username`, same as bookmarks -- each user's
calendar is private to them.

## Reminder sync API

`GET /api/reminder` / `POST /api/reminder` (form field `content`) let the
separate MyReminder Android app read/write the oldest sticky note without
going through the Telegram login flow -- auth is a shared secret header
(`X-API-Key`) instead of a session cookie. Both `REMINDER_API_KEY` and
`REMINDER_API_USERNAME` must be set in `.env` or the routes 503. `POST`
creates the first sticky note if the user has none yet, otherwise updates the
oldest one.

## Running locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # -r requirements.txt is enough outside dev

cp .env.example .env
# edit .env: TELEGRAM_BOT_TOKEN (reuse the bot from app_bookmarks) and a
# random SESSION_SECRET, e.g. `python -c "import secrets; print(secrets.token_hex(32))"`

python scripts/seed_user.py juan <your-telegram-chat-id>

uvicorn bookmarks_pi.main:app --reload
# open http://localhost:8000
```

## Tests

```bash
pytest
```

Covers `db.py` (login-code lifecycle, single-use, expiry, per-owner bookmark
scoping) and `telegram.py` (the Telegram API call, mocked with `respx`) --
no FastAPI integration test yet, the routes are thin enough to eyeball.

## Deploying on the Raspberry Pi

```bash
# on the Pi
git clone <this repo> app_bookmarks_pi && cd app_bookmarks_pi
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in TELEGRAM_BOT_TOKEN and SESSION_SECRET

sudo cp deploy/bookmarks-pi.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bookmarks-pi
```

The service binds `0.0.0.0:8000` (see `deploy/bookmarks-pi.service`), so it's
reachable from any device on the LAN at `http://<pi-ip>:8000` right away.

### Accessing it from outside your home network

Pick one, roughly in order of how much you should trust exposing a personal
Raspberry Pi directly to the internet:

- **Tailscale / WireGuard (recommended)** -- put the Pi on a private VPN and
  reach it as if it were on your LAN, from your phone or laptop, anywhere.
  No open ports on your router at all.
- **Cloudflare Tunnel** -- outbound-only tunnel from the Pi, gives you a
  public HTTPS URL without forwarding any port on your router.
- **Router port-forward + Dynamic DNS** -- forwards a port straight to the
  Pi. Works, but then this app is directly internet-facing with only the
  Telegram login code standing between it and the world -- put a reverse
  proxy (Caddy/nginx) in front for HTTPS at minimum if you go this route.

This repo doesn't set any of these up -- pick one when you're actually ready
to deploy, since it's a decision about your home network, not the app.

## Status

Scaffolded: passwordless login (request code -> Telegram -> verify -> session
cookie), bookmark create/list/filter-by-category, a per-user calendar
(birthdays, vacations, auto-computed work-shift rest days) rendered above the
bookmark list, SQLite schema, seed script, systemd unit example. Not run
against a real Telegram bot yet -- next step is to fill in `.env` with the
real token, seed a user, and walk the happy path locally before deploying to
the Pi.
