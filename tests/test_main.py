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

TABLES = ["users", "login_codes", "bookmarks", "birthdays", "vacations", "holidays", "work_shifts", "category_order"]


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
    assert 'id="calendar-settings" open' in r.text


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
    assert 'id="calendar-settings" open' not in r.text


def test_edit_bookmark_updates_it_and_redirects_to_new_category_anchor(client):
    client.post("/bookmarks", data={"category": "reading", "name": "Blog", "url": "https://blog.dev"})
    conn = db.open_connection(main.settings.database_path)
    bookmark_id = db.list_bookmarks(conn, "juan")[0]["id"]
    conn.close()

    r = client.post(
        f"/bookmarks/{bookmark_id}/edit",
        data={"category": "tools", "name": "New name", "url": "https://new.dev"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].endswith("#category-tools")

    conn = db.open_connection(main.settings.database_path)
    updated = db.get_bookmark(conn, "juan", bookmark_id)
    conn.close()
    assert updated["category"] == "tools"
    assert updated["name"] == "New name"


def test_bookmark_edit_modal_is_present_and_hidden_by_default(client):
    client.post("/bookmarks", data={"category": "reading", "name": "Blog", "url": "https://blog.dev"})
    conn = db.open_connection(main.settings.database_path)
    bookmark_id = db.list_bookmarks(conn, "juan")[0]["id"]
    conn.close()

    r = client.get("/bookmarks")
    assert f'id="edit-bookmark-{bookmark_id}"' in r.text
    assert f'action="/bookmarks/{bookmark_id}/edit"' in r.text
    assert f'href="#edit-bookmark-{bookmark_id}"' in r.text


def test_deleting_already_gone_row_does_not_error(client):
    r = client.post("/calendar/birthdays/999/delete")
    assert r.status_code == 200
    assert "Undo" not in r.text


def test_manage_panel_stays_open_after_adding_a_holiday(client):
    r = client.post("/calendar/holidays", data={"title": "Andalucía", "day": "28", "month": "2"})
    assert r.status_code == 200
    assert 'id="calendar-settings" open' in r.text


def test_bookmark_list_truncates_to_five_with_show_more(client):
    for i in range(7):
        client.post("/bookmarks", data={"category": "apps", "name": f"Link {i}", "url": f"https://{i}.dev"})

    r = client.get("/bookmarks")
    assert r.text.count("Delete Link") == 7  # all rendered, just some inside <details>
    assert "Show 2 more" in r.text
    assert 'class="bookmark-more"' in r.text


def test_bookmark_list_has_no_show_more_at_five_or_fewer(client):
    for i in range(5):
        client.post("/bookmarks", data={"category": "apps", "name": f"Link {i}", "url": f"https://{i}.dev"})

    r = client.get("/bookmarks")
    assert "Show" not in r.text
    assert 'class="bookmark-more"' not in r.text


def test_manage_bookmarks_panel_stays_open_after_adding_a_bookmark(client):
    r = client.post("/bookmarks", data={"category": "apps", "name": "Example", "url": "https://example.com"})
    assert r.status_code == 200
    assert 'id="bookmarks-settings" open' in r.text
    assert 'id="calendar-settings" open' not in r.text


def test_manage_bookmarks_panel_is_collapsed_by_default(client):
    r = client.get("/bookmarks")
    assert 'id="bookmarks-settings" open' not in r.text
    assert "Manage bookmarks" in r.text


def test_move_category_reorders_bookmark_sections(client):
    client.post("/bookmarks", data={"category": "apps", "name": "A", "url": "https://a.dev"})
    client.post("/bookmarks", data={"category": "sports", "name": "B", "url": "https://b.dev"})

    r = client.post("/bookmarks/categories/move", data={"category": "sports", "direction": "up"})
    assert r.status_code == 200
    assert r.text.index(">sports<") < r.text.index(">apps<")


def test_reorder_categories_endpoint_sets_full_order(client):
    client.post("/bookmarks", data={"category": "apps", "name": "A", "url": "https://a.dev"})
    client.post("/bookmarks", data={"category": "sports", "name": "B", "url": "https://b.dev"})
    client.post("/bookmarks", data={"category": "youtube", "name": "C", "url": "https://c.dev"})

    r = client.post("/bookmarks/categories/reorder", data={"category": ["youtube", "apps", "sports"]})
    assert r.status_code == 200
    positions = [r.text.index(f">{c}<") for c in ("youtube", "apps", "sports")]
    assert positions == sorted(positions)


def test_reorder_bookmarks_endpoint_sets_order_within_category(client):
    client.post("/bookmarks", data={"category": "apps", "name": "A", "url": "https://a.dev"})
    client.post("/bookmarks", data={"category": "apps", "name": "B", "url": "https://b.dev"})
    conn = db.open_connection(main.settings.database_path)
    ids = [b["id"] for b in db.list_bookmarks(conn, "juan", category="apps")]
    conn.close()
    # list_bookmarks (by created_at) returns newest first: [B, A] -- reorder to A, B
    reordered_ids = list(reversed(ids))

    r = client.post(
        "/bookmarks/reorder",
        data={"category": "apps", "id": [str(i) for i in reordered_ids]},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].endswith("#category-apps")

    conn = db.open_connection(main.settings.database_path)
    grouped = db.list_bookmarks_grouped_by_category(conn, "juan")
    conn.close()
    assert [b["id"] for b in grouped["apps"]] == reordered_ids


def test_reorder_bookmarks_reopens_show_more_when_it_was_open(client):
    for i in range(7):
        client.post("/bookmarks", data={"category": "apps", "name": f"Link {i}", "url": f"https://{i}.dev"})
    conn = db.open_connection(main.settings.database_path)
    ids = [b["id"] for b in db.list_bookmarks(conn, "juan", category="apps")]
    conn.close()

    r = client.post(
        "/bookmarks/reorder",
        data={"category": "apps", "id": [str(i) for i in ids], "open_more": "1"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "open_more=apps" in r.headers["location"]

    r = client.get(r.headers["location"].split("#")[0])
    assert '<details class="bookmark-more" open>' in r.text


def test_reorder_bookmarks_leaves_show_more_closed_when_it_was_closed(client):
    for i in range(7):
        client.post("/bookmarks", data={"category": "apps", "name": f"Link {i}", "url": f"https://{i}.dev"})
    conn = db.open_connection(main.settings.database_path)
    ids = [b["id"] for b in db.list_bookmarks(conn, "juan", category="apps")]
    conn.close()

    r = client.post(
        "/bookmarks/reorder",
        data={"category": "apps", "id": [str(i) for i in ids]},
        follow_redirects=False,
    )
    assert "open_more" not in r.headers["location"]

    r = client.get(r.headers["location"].split("#")[0])
    assert '<details class="bookmark-more" >' in r.text


def test_slugify_produces_url_safe_ids():
    assert main.slugify("apps") == "apps"
    assert main.slugify("Cool Apps!") == "cool-apps"
    assert main.slugify("  spaced  out  ") == "spaced-out"
    assert main.slugify("") == "category"
    assert main.slugify("!!!") == "category"


def test_deleting_a_bookmark_redirects_to_its_category_anchor(client):
    client.post("/bookmarks", data={"category": "Cool Apps!", "name": "Example", "url": "https://example.com"})
    conn = db.open_connection(main.settings.database_path)
    bookmark_id = db.list_bookmarks(conn, "juan")[0]["id"]
    conn.close()

    r = client.post(f"/bookmarks/{bookmark_id}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].endswith("#category-cool-apps")


def test_deleting_a_birthday_redirects_to_the_calendar_anchor(client):
    client.post("/calendar/birthdays", data={"title": "Alex", "day": "6", "month": "1"})
    conn = db.open_connection(main.settings.database_path)
    birthday_id = db.list_birthdays(conn, "juan")[0]["id"]
    conn.close()

    r = client.post(f"/calendar/birthdays/{birthday_id}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].endswith("#calendar-settings")


def test_moving_a_category_redirects_to_its_own_anchor(client):
    client.post("/bookmarks", data={"category": "apps", "name": "A", "url": "https://a.dev"})
    client.post("/bookmarks", data={"category": "sports", "name": "B", "url": "https://b.dev"})

    r = client.post("/bookmarks/categories/move", data={"category": "sports", "direction": "up"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].endswith("#category-sports")
