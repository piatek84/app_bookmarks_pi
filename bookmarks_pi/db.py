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

CREATE TABLE IF NOT EXISTS birthdays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_username TEXT NOT NULL,
    title TEXT NOT NULL,
    month INTEGER NOT NULL,
    day INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_birthdays_owner ON birthdays (owner_username);

CREATE TABLE IF NOT EXISTS vacations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_username TEXT NOT NULL,
    title TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vacations_owner ON vacations (owner_username);

CREATE TABLE IF NOT EXISTS work_shifts (
    owner_username TEXT PRIMARY KEY,
    start_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS holidays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_username TEXT NOT NULL,
    title TEXT NOT NULL,
    month INTEGER NOT NULL,
    day INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_holidays_owner ON holidays (owner_username);
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


def get_bookmark(conn: sqlite3.Connection, owner_username: str, bookmark_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM bookmarks WHERE id = ? AND owner_username = ?",
        (bookmark_id, owner_username),
    ).fetchone()


def delete_bookmark(conn: sqlite3.Connection, owner_username: str, bookmark_id: int) -> bool:
    cursor = conn.execute(
        "DELETE FROM bookmarks WHERE id = ? AND owner_username = ?",
        (bookmark_id, owner_username),
    )
    conn.commit()
    return cursor.rowcount > 0


def list_categories(conn: sqlite3.Connection, owner_username: str) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT category FROM bookmarks WHERE owner_username = ? ORDER BY category",
        (owner_username,),
    ).fetchall()
    return [row["category"] for row in rows]


def list_bookmarks_grouped_by_category(conn: sqlite3.Connection, owner_username: str) -> dict[str, list[sqlite3.Row]]:
    rows = conn.execute(
        "SELECT * FROM bookmarks WHERE owner_username = ? ORDER BY category, created_at DESC",
        (owner_username,),
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["category"], []).append(row)
    return grouped


def create_birthday(conn: sqlite3.Connection, owner_username: str, title: str, month: int, day: int) -> sqlite3.Row:
    cursor = conn.execute(
        "INSERT INTO birthdays (owner_username, title, month, day, created_at) VALUES (?, ?, ?, ?, ?)",
        (owner_username, title, month, day, _now()),
    )
    conn.commit()
    return conn.execute("SELECT * FROM birthdays WHERE id = ?", (cursor.lastrowid,)).fetchone()


def list_birthdays(conn: sqlite3.Connection, owner_username: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM birthdays WHERE owner_username = ? ORDER BY month, day",
        (owner_username,),
    ).fetchall()


def get_birthday(conn: sqlite3.Connection, owner_username: str, birthday_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM birthdays WHERE id = ? AND owner_username = ?",
        (birthday_id, owner_username),
    ).fetchone()


def delete_birthday(conn: sqlite3.Connection, owner_username: str, birthday_id: int) -> bool:
    cursor = conn.execute(
        "DELETE FROM birthdays WHERE id = ? AND owner_username = ?",
        (birthday_id, owner_username),
    )
    conn.commit()
    return cursor.rowcount > 0


def create_vacation(conn: sqlite3.Connection, owner_username: str, title: str, start_date: str, end_date: str) -> sqlite3.Row:
    cursor = conn.execute(
        "INSERT INTO vacations (owner_username, title, start_date, end_date, created_at) VALUES (?, ?, ?, ?, ?)",
        (owner_username, title, start_date, end_date, _now()),
    )
    conn.commit()
    return conn.execute("SELECT * FROM vacations WHERE id = ?", (cursor.lastrowid,)).fetchone()


def list_vacations(conn: sqlite3.Connection, owner_username: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM vacations WHERE owner_username = ? ORDER BY start_date",
        (owner_username,),
    ).fetchall()


def get_vacation(conn: sqlite3.Connection, owner_username: str, vacation_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM vacations WHERE id = ? AND owner_username = ?",
        (vacation_id, owner_username),
    ).fetchone()


def delete_vacation(conn: sqlite3.Connection, owner_username: str, vacation_id: int) -> bool:
    cursor = conn.execute(
        "DELETE FROM vacations WHERE id = ? AND owner_username = ?",
        (vacation_id, owner_username),
    )
    conn.commit()
    return cursor.rowcount > 0


def create_holiday(conn: sqlite3.Connection, owner_username: str, title: str, month: int, day: int) -> sqlite3.Row:
    cursor = conn.execute(
        "INSERT INTO holidays (owner_username, title, month, day, created_at) VALUES (?, ?, ?, ?, ?)",
        (owner_username, title, month, day, _now()),
    )
    conn.commit()
    return conn.execute("SELECT * FROM holidays WHERE id = ?", (cursor.lastrowid,)).fetchone()


def list_holidays(conn: sqlite3.Connection, owner_username: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM holidays WHERE owner_username = ? ORDER BY month, day",
        (owner_username,),
    ).fetchall()


def get_holiday(conn: sqlite3.Connection, owner_username: str, holiday_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM holidays WHERE id = ? AND owner_username = ?",
        (holiday_id, owner_username),
    ).fetchone()


def delete_holiday(conn: sqlite3.Connection, owner_username: str, holiday_id: int) -> bool:
    cursor = conn.execute(
        "DELETE FROM holidays WHERE id = ? AND owner_username = ?",
        (holiday_id, owner_username),
    )
    conn.commit()
    return cursor.rowcount > 0


def set_work_shift_start(conn: sqlite3.Connection, owner_username: str, start_date: str) -> None:
    conn.execute(
        """INSERT INTO work_shifts (owner_username, start_date) VALUES (?, ?)
           ON CONFLICT(owner_username) DO UPDATE SET start_date = excluded.start_date""",
        (owner_username, start_date),
    )
    conn.commit()


def get_work_shift_start(conn: sqlite3.Connection, owner_username: str) -> Optional[str]:
    row = conn.execute(
        "SELECT start_date FROM work_shifts WHERE owner_username = ?",
        (owner_username,),
    ).fetchone()
    return row["start_date"] if row else None
