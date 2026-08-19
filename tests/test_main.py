"""Integration tests for the FastAPI routes -- mainly the delete -> undo
toast -> restore round trip and the "keep the manage panel open" behaviour,
since those are stitched together through redirect query params rather than
a database flag.
"""
import os
import tempfile
from unittest.mock import patch

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy:token")
os.environ.setdefault("SESSION_SECRET", "dummy-secret-for-tests")
os.environ.setdefault("DATABASE_PATH", tempfile.mktemp(suffix=".db"))

import pytest
from starlette.testclient import TestClient

from bookmarks_pi import db, main

TABLES = ["users", "login_codes", "bookmarks", "birthdays", "vacations", "holidays", "work_shifts"]


@pytest.fixture
def client():
    conn = db.open_connection(main.settings.database_path)
    for table in TABLES:
        conn.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()

    db.create_user(db.open_connection(main.settings.database_path), "juan", 12345)

    test_client = TestClient(main.app)
    with patch("bookmarks_pi.main.telegram.send_message"):
        test_client.post("/login", data={"username": "juan"})
    conn = db.open_connection(main.settings.database_path)
    code = conn.execute("SELECT code FROM login_codes ORDER BY id DESC LIMIT 1").fetchone()["code"]
    conn.close()
    test_client.post("/verify", data={"username": "juan", "code": code})
    return test_client


def test_delete_birthday_shows_undo_toast_and_keeps_panel_open(client):
    client.post("/calendar/birthdays", data={"title": "Alex", "day": "6", "month": "1"})
    conn = db.open_connection(main.settings.database_path)
    birthday_id = db.list_birthdays(conn, "juan")[0]["id"]
    conn.close()

    r = client.post(f"/calendar/birthdays/{birthday_id}/delete")
    assert r.status_code == 200  # TestClient follows the redirect

    conn = db.open_connection(main.settings.database_path)
    assert db.list_birthdays(conn, "juan") == []
    conn.close()

    assert "Undo" in r.text
    assert 'action="/calendar/birthdays/restore"' in r.text
    assert 'class="calendar-settings" open' in r.text


def test_undo_restores_deleted_birthday(client):
    client.post("/calendar/birthdays", data={"title": "Alex", "day": "6", "month": "1"})
    conn = db.open_connection(main.settings.database_path)
    birthday_id = db.list_birthdays(conn, "juan")[0]["id"]
    conn.close()
    client.post(f"/calendar/birthdays/{birthday_id}/delete")

    r = client.post("/calendar/birthdays/restore", data={"title": "Alex", "day": "6", "month": "1"})
    assert r.status_code == 200

    conn = db.open_connection(main.settings.database_path)
    restored = db.list_birthdays(conn, "juan")
    conn.close()
    assert [b["title"] for b in restored] == ["Alex"]


def test_delete_bookmark_shows_undo_toast_without_open_manage(client):
    client.post("/bookmarks", data={"category": "tools", "name": "Example", "url": "https://example.com"})
    conn = db.open_connection(main.settings.database_path)
    bookmark_id = db.list_bookmarks(conn, "juan")[0]["id"]
    conn.close()

    r = client.post(f"/bookmarks/{bookmark_id}/delete")
    assert r.status_code == 200
    assert 'action="/bookmarks/restore"' in r.text
    assert 'class="calendar-settings" open' not in r.text


def test_deleting_already_gone_row_does_not_error(client):
    r = client.post("/calendar/birthdays/999/delete")
    assert r.status_code == 200
    assert "Undo" not in r.text


def test_manage_panel_stays_open_after_adding_a_holiday(client):
    r = client.post("/calendar/holidays", data={"title": "Andalucía", "day": "28", "month": "2"})
    assert r.status_code == 200
    assert 'class="calendar-settings" open' in r.text
