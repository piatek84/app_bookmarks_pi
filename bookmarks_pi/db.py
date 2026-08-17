"""Plain sqlite3 access layer -- no ORM. Single-household app on a Raspberry
Pi doesn't need connection pooling or a migrations framework.
"""
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    telegram_chat_id INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    code TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_username TEXT NOT NULL,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_owner_category
    ON bookmarks (owner_username, category);
"""


def init_db(database_path: str) -> None:
    if database_path != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def open_connection(database_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_user(conn: sqlite3.Connection, username: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def create_user(conn: sqlite3.Connection, username: str, telegram_chat_id: int) -> None:
    conn.execute(
        "INSERT INTO users (username, telegram_chat_id, created_at) VALUES (?, ?, ?)",
        (username, telegram_chat_id, _now()),
    )
    conn.commit()


def create_login_code(conn: sqlite3.Connection, username: str, ttl_seconds: int, length: int) -> str:
    code = "".join(str(secrets.randbelow(10)) for _ in range(length))
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()
    conn.execute(
        "INSERT INTO login_codes (username, code, used, expires_at, created_at) VALUES (?, ?, 0, ?, ?)",
        (username, code, expires_at, _now()),
    )
    conn.commit()
    return code


def verify_login_code(conn: sqlite3.Connection, username: str, code: str) -> bool:
    row = conn.execute(
        """SELECT id, expires_at FROM login_codes
           WHERE username = ? AND code = ? AND used = 0
           ORDER BY id DESC LIMIT 1""",
        (username, code),
    ).fetchone()
    if row is None:
        return False
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        return False
    conn.execute("UPDATE login_codes SET used = 1 WHERE id = ?", (row["id"],))
    conn.commit()
    return True


def create_bookmark(conn: sqlite3.Connection, owner_username: str, category: str, name: str, url: str) -> sqlite3.Row:
    cursor = conn.execute(
        "INSERT INTO bookmarks (owner_username, category, name, url, created_at) VALUES (?, ?, ?, ?, ?)",
        (owner_username, category, name, url, _now()),
    )
    conn.commit()
    return conn.execute("SELECT * FROM bookmarks WHERE id = ?", (cursor.lastrowid,)).fetchone()


def list_bookmarks(conn: sqlite3.Connection, owner_username: str, category: Optional[str] = None) -> list[sqlite3.Row]:
    if category:
        return conn.execute(
            "SELECT * FROM bookmarks WHERE owner_username = ? AND category = ? ORDER BY created_at DESC",
            (owner_username, category),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM bookmarks WHERE owner_username = ? ORDER BY created_at DESC",
        (owner_username,),
    ).fetchall()


def list_categories(conn: sqlite3.Connection, owner_username: str) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT category FROM bookmarks WHERE owner_username = ? ORDER BY category",
        (owner_username,),
    ).fetchall()
    return [row["category"] for row in rows]
