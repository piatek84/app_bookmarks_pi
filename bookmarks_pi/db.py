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
    position INTEGER,
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
    start_date TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS shift_blocks (
    owner_username TEXT NOT NULL,
    block_start TEXT NOT NULL,
    shift_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (owner_username, block_start)
);
CREATE INDEX IF NOT EXISTS idx_shift_blocks_owner ON shift_blocks (owner_username);

CREATE TABLE IF NOT EXISTS holidays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_username TEXT NOT NULL,
    title TEXT NOT NULL,
    month INTEGER NOT NULL,
    day INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_holidays_owner ON holidays (owner_username);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_username TEXT NOT NULL,
    title TEXT NOT NULL,
    task_date TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_owner ON tasks (owner_username);

CREATE TABLE IF NOT EXISTS category_order (
    owner_username TEXT NOT NULL,
    category TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (owner_username, category)
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_username TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    original_name TEXT NOT NULL,
    size INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_owner ON documents (owner_username);

CREATE TABLE IF NOT EXISTS sticky_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_username TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sticky_notes_owner ON sticky_notes (owner_username);
"""


def init_db(database_path: str) -> None:
    if database_path != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path)
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Adds columns that postdate CREATE TABLE IF NOT EXISTS, for databases
    created by an earlier version of this app."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(bookmarks)").fetchall()}
    if "position" not in columns:
        conn.execute("ALTER TABLE bookmarks ADD COLUMN position INTEGER")

    shift_columns = {row[1] for row in conn.execute("PRAGMA table_info(work_shifts)").fetchall()}
    if "enabled" not in shift_columns:
        conn.execute("ALTER TABLE work_shifts ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")


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


def _ensure_category_position(conn: sqlite3.Connection, owner_username: str, category: str) -> None:
    existing = conn.execute(
        "SELECT 1 FROM category_order WHERE owner_username = ? AND category = ?",
        (owner_username, category),
    ).fetchone()
    if existing:
        return
    max_position = conn.execute(
        "SELECT COALESCE(MAX(position), -1) AS m FROM category_order WHERE owner_username = ?",
        (owner_username,),
    ).fetchone()["m"]
    conn.execute(
        "INSERT INTO category_order (owner_username, category, position) VALUES (?, ?, ?)",
        (owner_username, category, max_position + 1),
    )


def _sync_category_positions(conn: sqlite3.Connection, owner_username: str) -> None:
    """Backfills positions for categories that predate this table (legacy data,
    imports) so they still show up, appended in alphabetical order. Also drops
    stale rows for categories that no longer have any bookmark (deleted,
    renamed, or a stray leftover from a typo) so they don't keep cluttering
    the order forever."""
    known = {
        row["category"]
        for row in conn.execute(
            "SELECT category FROM category_order WHERE owner_username = ?", (owner_username,)
        ).fetchall()
    }
    all_categories = [
        row["category"]
        for row in conn.execute(
            "SELECT DISTINCT category FROM bookmarks WHERE owner_username = ? ORDER BY category",
            (owner_username,),
        ).fetchall()
    ]
    for category in all_categories:
        if category not in known:
            _ensure_category_position(conn, owner_username, category)
    conn.execute(
        """DELETE FROM category_order
           WHERE owner_username = ?
             AND category NOT IN (
                 SELECT DISTINCT category FROM bookmarks WHERE owner_username = ?
             )""",
        (owner_username, owner_username),
    )
    conn.commit()


def move_category(conn: sqlite3.Connection, owner_username: str, category: str, direction: int) -> None:
    """direction: -1 moves the category earlier, +1 moves it later.

    Only considers categories that currently have at least one bookmark:
    category_order keeps a row for every category ever used, even after its
    last bookmark is deleted or recategorized, so ignoring that filter would
    swap against invisible "ghost" categories and appear to do nothing.

    Renumbers every visible category sequentially afterwards instead of
    swapping the two raw position values: stale data can leave two
    categories sharing the same position (e.g. from an old reorder that
    skipped one of them), and swapping two equal values is a no-op that
    looks like the button did nothing. Renumbering also self-heals that
    corruption for the rest of the list on every move.
    """
    _sync_category_positions(conn, owner_username)
    rows = conn.execute(
        """SELECT co.category FROM category_order co
           WHERE co.owner_username = ?
             AND EXISTS (
                 SELECT 1 FROM bookmarks b
                 WHERE b.owner_username = co.owner_username AND b.category = co.category
             )
           ORDER BY co.position, co.category""",
        (owner_username,),
    ).fetchall()
    categories = [row["category"] for row in rows]
    if category not in categories:
        return
    index = categories.index(category)
    swap_index = index + direction
    if swap_index < 0 or swap_index >= len(categories):
        return
    categories[index], categories[swap_index] = categories[swap_index], categories[index]
    for position, cat in enumerate(categories):
        conn.execute(
            "UPDATE category_order SET position = ? WHERE owner_username = ? AND category = ?",
            (position, owner_username, cat),
        )
    conn.commit()


def reorder_categories(conn: sqlite3.Connection, owner_username: str, ordered_categories: list[str]) -> None:
    for index, category in enumerate(ordered_categories):
        conn.execute(
            """INSERT INTO category_order (owner_username, category, position) VALUES (?, ?, ?)
               ON CONFLICT(owner_username, category) DO UPDATE SET position = excluded.position""",
            (owner_username, category, index),
        )
    conn.commit()


def _next_bookmark_position(conn: sqlite3.Connection, owner_username: str, category: str) -> int:
    max_position = conn.execute(
        "SELECT COALESCE(MAX(position), -1) AS m FROM bookmarks WHERE owner_username = ? AND category = ?",
        (owner_username, category),
    ).fetchone()["m"]
    return max_position + 1


def create_bookmark(conn: sqlite3.Connection, owner_username: str, category: str, name: str, url: str) -> sqlite3.Row:
    position = _next_bookmark_position(conn, owner_username, category)
    cursor = conn.execute(
        "INSERT INTO bookmarks (owner_username, category, name, url, position, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (owner_username, category, name, url, position, _now()),
    )
    _ensure_category_position(conn, owner_username, category)
    conn.commit()
    return conn.execute("SELECT * FROM bookmarks WHERE id = ?", (cursor.lastrowid,)).fetchone()


def reorder_bookmarks(conn: sqlite3.Connection, owner_username: str, category: str, ordered_ids: list[int]) -> None:
    for index, bookmark_id in enumerate(ordered_ids):
        conn.execute(
            "UPDATE bookmarks SET position = ? WHERE id = ? AND owner_username = ? AND category = ?",
            (index, bookmark_id, owner_username, category),
        )
    conn.commit()


def move_bookmark(
    conn: sqlite3.Connection, owner_username: str, bookmark_id: int, category: str, ordered_ids: list[int]
) -> bool:
    """Drags `bookmark_id` into `category` (possibly its current one) and applies
    `ordered_ids` -- the full drop-target list's new id order -- as positions."""
    existing = get_bookmark(conn, owner_username, bookmark_id)
    if existing is None:
        return False
    conn.execute(
        "UPDATE bookmarks SET category = ? WHERE id = ? AND owner_username = ?",
        (category, bookmark_id, owner_username),
    )
    for index, bid in enumerate(ordered_ids):
        conn.execute(
            "UPDATE bookmarks SET position = ? WHERE id = ? AND owner_username = ? AND category = ?",
            (index, bid, owner_username, category),
        )
    _ensure_category_position(conn, owner_username, category)
    conn.commit()
    return True


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


def update_bookmark(
    conn: sqlite3.Connection, owner_username: str, bookmark_id: int, category: str, name: str, url: str
) -> bool:
    existing = get_bookmark(conn, owner_username, bookmark_id)
    if existing is None:
        return False
    if existing["category"] != category:
        position = _next_bookmark_position(conn, owner_username, category)
        conn.execute(
            "UPDATE bookmarks SET category = ?, name = ?, url = ?, position = ? WHERE id = ? AND owner_username = ?",
            (category, name, url, position, bookmark_id, owner_username),
        )
    else:
        conn.execute(
            "UPDATE bookmarks SET category = ?, name = ?, url = ? WHERE id = ? AND owner_username = ?",
            (category, name, url, bookmark_id, owner_username),
        )
    _ensure_category_position(conn, owner_username, category)
    conn.commit()
    return True


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


def _sync_bookmark_positions(conn: sqlite3.Connection, owner_username: str) -> None:
    """Backfills positions for bookmarks that predate the position column
    (legacy data, imports), preserving their previous created_at-DESC order."""
    rows = conn.execute(
        """SELECT id, category FROM bookmarks
           WHERE owner_username = ? AND position IS NULL
           ORDER BY category, created_at DESC""",
        (owner_username,),
    ).fetchall()
    next_position: dict[str, int] = {}
    for row in rows:
        category = row["category"]
        if category not in next_position:
            next_position[category] = _next_bookmark_position(conn, owner_username, category)
        conn.execute("UPDATE bookmarks SET position = ? WHERE id = ?", (next_position[category], row["id"]))
        next_position[category] += 1
    if rows:
        conn.commit()


def list_bookmarks_grouped_by_category(conn: sqlite3.Connection, owner_username: str) -> dict[str, list[sqlite3.Row]]:
    _sync_category_positions(conn, owner_username)
    _sync_bookmark_positions(conn, owner_username)
    order = [
        row["category"]
        for row in conn.execute(
            "SELECT category FROM category_order WHERE owner_username = ? ORDER BY position, category",
            (owner_username,),
        ).fetchall()
    ]
    rows = conn.execute(
        "SELECT * FROM bookmarks WHERE owner_username = ? ORDER BY position ASC",
        (owner_username,),
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["category"], []).append(row)
    return {category: grouped[category] for category in order if category in grouped}


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


def create_task(conn: sqlite3.Connection, owner_username: str, title: str, task_date: str) -> sqlite3.Row:
    cursor = conn.execute(
        "INSERT INTO tasks (owner_username, title, task_date, created_at) VALUES (?, ?, ?, ?)",
        (owner_username, title, task_date, _now()),
    )
    conn.commit()
    return conn.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()


def list_tasks(conn: sqlite3.Connection, owner_username: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM tasks WHERE owner_username = ? ORDER BY task_date",
        (owner_username,),
    ).fetchall()


def get_task(conn: sqlite3.Connection, owner_username: str, task_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM tasks WHERE id = ? AND owner_username = ?",
        (task_id, owner_username),
    ).fetchone()


def delete_task(conn: sqlite3.Connection, owner_username: str, task_id: int) -> bool:
    cursor = conn.execute(
        "DELETE FROM tasks WHERE id = ? AND owner_username = ?",
        (task_id, owner_username),
    )
    conn.commit()
    return cursor.rowcount > 0


def set_work_shift(conn: sqlite3.Connection, owner_username: str, start_date: str, enabled: bool) -> None:
    conn.execute(
        """INSERT INTO work_shifts (owner_username, start_date, enabled) VALUES (?, ?, ?)
           ON CONFLICT(owner_username) DO UPDATE SET start_date = excluded.start_date, enabled = excluded.enabled""",
        (owner_username, start_date, 1 if enabled else 0),
    )
    conn.commit()


SHIFT_TYPES = ("morning", "afternoon", "night")
DEFAULT_SHIFT_TYPE = "morning"


def set_shift_block(conn: sqlite3.Connection, owner_username: str, block_start: str, shift_type: str) -> sqlite3.Row:
    conn.execute(
        """INSERT INTO shift_blocks (owner_username, block_start, shift_type, created_at) VALUES (?, ?, ?, ?)
           ON CONFLICT(owner_username, block_start) DO UPDATE SET shift_type = excluded.shift_type""",
        (owner_username, block_start, shift_type, _now()),
    )
    conn.commit()
    return conn.execute(
        "SELECT * FROM shift_blocks WHERE owner_username = ? AND block_start = ?",
        (owner_username, block_start),
    ).fetchone()


def list_shift_blocks(conn: sqlite3.Connection, owner_username: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM shift_blocks WHERE owner_username = ? ORDER BY block_start",
        (owner_username,),
    ).fetchall()


def delete_shift_block(conn: sqlite3.Connection, owner_username: str, block_start: str) -> bool:
    cursor = conn.execute(
        "DELETE FROM shift_blocks WHERE owner_username = ? AND block_start = ?",
        (owner_username, block_start),
    )
    conn.commit()
    return cursor.rowcount > 0


def create_document(
    conn: sqlite3.Connection, owner_username: str, stored_name: str, original_name: str, size: int
) -> sqlite3.Row:
    cursor = conn.execute(
        "INSERT INTO documents (owner_username, stored_name, original_name, size, created_at) VALUES (?, ?, ?, ?, ?)",
        (owner_username, stored_name, original_name, size, _now()),
    )
    conn.commit()
    return conn.execute("SELECT * FROM documents WHERE id = ?", (cursor.lastrowid,)).fetchone()


def list_documents(conn: sqlite3.Connection, owner_username: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM documents WHERE owner_username = ? ORDER BY created_at DESC",
        (owner_username,),
    ).fetchall()


def sync_documents_from_disk(conn: sqlite3.Connection, owner_username: str, user_dir: Path) -> None:
    """Register files dropped into the user's upload folder outside the app (e.g. via SSH/Samba)."""
    if not user_dir.is_dir():
        return
    existing = {
        row["stored_name"]
        for row in conn.execute(
            "SELECT stored_name FROM documents WHERE owner_username = ?", (owner_username,)
        ).fetchall()
    }
    for entry in sorted(user_dir.iterdir()):
        if not entry.is_file() or entry.name.startswith(".") or entry.name in existing:
            continue
        stat = entry.stat()
        created_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO documents (owner_username, stored_name, original_name, size, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (owner_username, entry.name, entry.name, stat.st_size, created_at),
        )
    conn.commit()


def get_document(conn: sqlite3.Connection, owner_username: str, document_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM documents WHERE id = ? AND owner_username = ?",
        (document_id, owner_username),
    ).fetchone()


def delete_document(conn: sqlite3.Connection, owner_username: str, document_id: int) -> bool:
    cursor = conn.execute(
        "DELETE FROM documents WHERE id = ? AND owner_username = ?",
        (document_id, owner_username),
    )
    conn.commit()
    return cursor.rowcount > 0


def create_sticky_note(conn: sqlite3.Connection, owner_username: str, content: str) -> sqlite3.Row:
    cursor = conn.execute(
        "INSERT INTO sticky_notes (owner_username, content, created_at) VALUES (?, ?, ?)",
        (owner_username, content, _now()),
    )
    conn.commit()
    return conn.execute("SELECT * FROM sticky_notes WHERE id = ?", (cursor.lastrowid,)).fetchone()


def list_sticky_notes(conn: sqlite3.Connection, owner_username: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM sticky_notes WHERE owner_username = ? ORDER BY created_at",
        (owner_username,),
    ).fetchall()


def update_sticky_note(conn: sqlite3.Connection, owner_username: str, note_id: int, content: str) -> bool:
    cursor = conn.execute(
        "UPDATE sticky_notes SET content = ? WHERE id = ? AND owner_username = ?",
        (content, note_id, owner_username),
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_sticky_note(conn: sqlite3.Connection, owner_username: str, note_id: int) -> bool:
    cursor = conn.execute(
        "DELETE FROM sticky_notes WHERE id = ? AND owner_username = ?",
        (note_id, owner_username),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_work_shift(conn: sqlite3.Connection, owner_username: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM work_shifts WHERE owner_username = ?",
        (owner_username,),
    ).fetchone()
