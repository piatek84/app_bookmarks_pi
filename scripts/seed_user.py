"""One-off CLI to create a user row -- there's no signup endpoint by design.

Usage:
    python scripts/seed_user.py <username> <telegram_chat_id>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bookmarks_pi import db
from bookmarks_pi.config import load_settings


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python scripts/seed_user.py <username> <telegram_chat_id>")
        raise SystemExit(1)

    username, chat_id = sys.argv[1], int(sys.argv[2])
    settings = load_settings()
    db.init_db(settings.database_path)
    conn = db.open_connection(settings.database_path)
    try:
        if db.get_user(conn, username):
            print(f'User "{username}" already exists.')
            return
        db.create_user(conn, username, chat_id)
        print(f'Created user "{username}" (telegram_chat_id={chat_id}).')
    finally:
        conn.close()


if __name__ == "__main__":
    main()
