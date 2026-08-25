import pytest

from bookmarks_pi import db


@pytest.fixture
def conn(tmp_path):
    database_path = str(tmp_path / "test.db")
    db.init_db(database_path)
    connection = db.open_connection(database_path)
    yield connection
    connection.close()


def test_init_db_adds_position_column_to_pre_existing_bookmarks_table(tmp_path):
    import sqlite3

    database_path = str(tmp_path / "legacy.db")
    legacy_conn = sqlite3.connect(database_path)
    legacy_conn.execute(
        """CREATE TABLE bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_username TEXT NOT NULL,
            category TEXT NOT NULL,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    legacy_conn.execute(
        "INSERT INTO bookmarks (owner_username, category, name, url, created_at) VALUES (?, ?, ?, ?, ?)",
        ("juan", "tools", "Old", "https://old.dev", "2020-01-01"),
    )
    legacy_conn.commit()
    legacy_conn.close()

    db.init_db(database_path)  # must not raise on a table missing the new column
    conn = db.open_connection(database_path)
    grouped = db.list_bookmarks_grouped_by_category(conn, "juan")
    assert [b["name"] for b in grouped["tools"]] == ["Old"]
    conn.close()


def test_create_and_get_user(conn):
    db.create_user(conn, "juan", 12345)
    user = db.get_user(conn, "juan")
    assert user["username"] == "juan"
    assert user["telegram_chat_id"] == 12345


def test_get_user_returns_none_when_missing(conn):
    assert db.get_user(conn, "ghost") is None


def test_login_code_round_trip(conn):
    db.create_user(conn, "juan", 12345)
    code = db.create_login_code(conn, "juan", ttl_seconds=300, length=6)
    assert len(code) == 6
    assert db.verify_login_code(conn, "juan", code) is True


def test_login_code_rejects_wrong_code(conn):
    db.create_user(conn, "juan", 12345)
    db.create_login_code(conn, "juan", ttl_seconds=300, length=6)
    assert db.verify_login_code(conn, "juan", "000000") is False


def test_login_code_is_single_use(conn):
    db.create_user(conn, "juan", 12345)
    code = db.create_login_code(conn, "juan", ttl_seconds=300, length=6)
    assert db.verify_login_code(conn, "juan", code) is True
    assert db.verify_login_code(conn, "juan", code) is False


def test_login_code_rejects_expired(conn):
    db.create_user(conn, "juan", 12345)
    code = db.create_login_code(conn, "juan", ttl_seconds=-1, length=6)
    assert db.verify_login_code(conn, "juan", code) is False


def test_bookmarks_crud_and_category_filter(conn):
    db.create_bookmark(conn, "juan", "reading", "Blog", "https://blog.dev")
    db.create_bookmark(conn, "juan", "tools", "Vite", "https://vite.dev")

    assert len(db.list_bookmarks(conn, "juan")) == 2

    reading_only = db.list_bookmarks(conn, "juan", category="reading")
    assert [b["name"] for b in reading_only] == ["Blog"]

    assert db.list_categories(conn, "juan") == ["reading", "tools"]


def test_bookmarks_are_scoped_per_owner(conn):
    db.create_bookmark(conn, "juan", "reading", "Blog", "https://blog.dev")
    assert db.list_bookmarks(conn, "other") == []


def test_delete_bookmark(conn):
    bookmark = db.create_bookmark(conn, "juan", "reading", "Blog", "https://blog.dev")
    assert db.delete_bookmark(conn, "juan", bookmark["id"]) is True
    assert db.list_bookmarks(conn, "juan") == []


def test_delete_bookmark_scoped_per_owner(conn):
    bookmark = db.create_bookmark(conn, "juan", "reading", "Blog", "https://blog.dev")
    assert db.delete_bookmark(conn, "other", bookmark["id"]) is False
    assert len(db.list_bookmarks(conn, "juan")) == 1


def test_update_bookmark(conn):
    bookmark = db.create_bookmark(conn, "juan", "reading", "Blog", "https://blog.dev")
    assert db.update_bookmark(conn, "juan", bookmark["id"], "tools", "New name", "https://new.dev") is True

    updated = db.get_bookmark(conn, "juan", bookmark["id"])
    assert updated["category"] == "tools"
    assert updated["name"] == "New name"
    assert updated["url"] == "https://new.dev"


def test_update_bookmark_registers_new_category_position(conn):
    bookmark = db.create_bookmark(conn, "juan", "reading", "Blog", "https://blog.dev")
    db.update_bookmark(conn, "juan", bookmark["id"], "brand-new-category", "Blog", "https://blog.dev")
    assert "brand-new-category" in db.list_bookmarks_grouped_by_category(conn, "juan")


def test_update_bookmark_scoped_per_owner(conn):
    bookmark = db.create_bookmark(conn, "juan", "reading", "Blog", "https://blog.dev")
    assert db.update_bookmark(conn, "other", bookmark["id"], "tools", "Hacked", "https://evil.dev") is False
    assert db.get_bookmark(conn, "juan", bookmark["id"])["name"] == "Blog"


def test_list_bookmarks_grouped_by_category(conn):
    db.create_bookmark(conn, "juan", "reading", "Blog", "https://blog.dev")
    db.create_bookmark(conn, "juan", "reading", "Feed", "https://feed.dev")
    db.create_bookmark(conn, "juan", "tools", "Vite", "https://vite.dev")

    grouped = db.list_bookmarks_grouped_by_category(conn, "juan")

    assert list(grouped.keys()) == ["reading", "tools"]
    assert [b["name"] for b in grouped["reading"]] == ["Blog", "Feed"]
    assert [b["name"] for b in grouped["tools"]] == ["Vite"]


def test_list_bookmarks_grouped_by_category_scoped_per_owner(conn):
    db.create_bookmark(conn, "juan", "reading", "Blog", "https://blog.dev")
    assert db.list_bookmarks_grouped_by_category(conn, "other") == {}


def test_categories_are_ordered_by_first_use(conn):
    db.create_bookmark(conn, "juan", "tools", "Vite", "https://vite.dev")
    db.create_bookmark(conn, "juan", "reading", "Blog", "https://blog.dev")
    db.create_bookmark(conn, "juan", "reading", "Feed", "https://feed.dev")

    grouped = db.list_bookmarks_grouped_by_category(conn, "juan")
    assert list(grouped.keys()) == ["tools", "reading"]


def test_reorder_categories_sets_explicit_order(conn):
    db.create_bookmark(conn, "juan", "apps", "A", "https://a.dev")
    db.create_bookmark(conn, "juan", "sports", "B", "https://b.dev")
    db.create_bookmark(conn, "juan", "youtube", "C", "https://c.dev")

    db.reorder_categories(conn, "juan", ["youtube", "apps", "sports"])
    assert list(db.list_bookmarks_grouped_by_category(conn, "juan").keys()) == ["youtube", "apps", "sports"]


def test_reorder_bookmarks_sets_explicit_order(conn):
    a = db.create_bookmark(conn, "juan", "apps", "A", "https://a.dev")
    b = db.create_bookmark(conn, "juan", "apps", "B", "https://b.dev")
    c = db.create_bookmark(conn, "juan", "apps", "C", "https://c.dev")

    db.reorder_bookmarks(conn, "juan", "apps", [c["id"], a["id"], b["id"]])
    grouped = db.list_bookmarks_grouped_by_category(conn, "juan")
    assert [bm["name"] for bm in grouped["apps"]] == ["C", "A", "B"]


def test_reorder_bookmarks_scoped_per_category(conn):
    a = db.create_bookmark(conn, "juan", "apps", "A", "https://a.dev")
    db.create_bookmark(conn, "juan", "apps", "B", "https://b.dev")
    other = db.create_bookmark(conn, "juan", "sports", "Other", "https://other.dev")

    # reordering "apps" must not touch a bookmark that lives in "sports"
    db.reorder_bookmarks(conn, "juan", "apps", [other["id"], a["id"]])
    assert db.get_bookmark(conn, "juan", other["id"])["category"] == "sports"


def test_updating_a_bookmark_into_a_new_category_appends_at_the_end(conn):
    db.create_bookmark(conn, "juan", "sports", "Existing", "https://existing.dev")
    moved = db.create_bookmark(conn, "juan", "apps", "Moved", "https://moved.dev")

    db.update_bookmark(conn, "juan", moved["id"], "sports", "Moved", "https://moved.dev")
    grouped = db.list_bookmarks_grouped_by_category(conn, "juan")
    assert [bm["name"] for bm in grouped["sports"]] == ["Existing", "Moved"]


def test_move_category_swaps_positions():
    conn = db.open_connection(":memory:")
    conn.executescript(db.SCHEMA)
    db.create_bookmark(conn, "juan", "apps", "A", "https://a.dev")
    db.create_bookmark(conn, "juan", "sports", "B", "https://b.dev")
    db.create_bookmark(conn, "juan", "youtube", "C", "https://c.dev")

    db.move_category(conn, "juan", "youtube", -1)
    assert list(db.list_bookmarks_grouped_by_category(conn, "juan").keys()) == ["apps", "youtube", "sports"]

    db.move_category(conn, "juan", "youtube", -1)
    assert list(db.list_bookmarks_grouped_by_category(conn, "juan").keys()) == ["youtube", "apps", "sports"]

    # already first: moving further up is a no-op
    db.move_category(conn, "juan", "youtube", -1)
    assert list(db.list_bookmarks_grouped_by_category(conn, "juan").keys()) == ["youtube", "apps", "sports"]

    db.move_category(conn, "juan", "youtube", 1)
    assert list(db.list_bookmarks_grouped_by_category(conn, "juan").keys()) == ["apps", "youtube", "sports"]


def test_move_category_backfills_positions_for_legacy_categories():
    conn = db.open_connection(":memory:")
    conn.executescript(db.SCHEMA)
    # simulate bookmarks that predate the category_order table
    conn.execute(
        "INSERT INTO bookmarks (owner_username, category, name, url, created_at) VALUES (?, ?, ?, ?, ?)",
        ("juan", "zzz-legacy", "Old", "https://old.dev", "2020-01-01"),
    )
    conn.execute(
        "INSERT INTO bookmarks (owner_username, category, name, url, created_at) VALUES (?, ?, ?, ?, ?)",
        ("juan", "aaa-legacy", "Older", "https://older.dev", "2020-01-01"),
    )
    conn.commit()

    db.move_category(conn, "juan", "zzz-legacy", -1)
    assert list(db.list_bookmarks_grouped_by_category(conn, "juan").keys()) == ["zzz-legacy", "aaa-legacy"]


def test_create_bookmark_normalizes_category(conn):
    db.create_bookmark(conn, "juan", "  Reading  ", "Blog", "https://blog.dev")
    assert db.list_categories(conn, "juan") == ["reading"]


def test_update_bookmark_normalizes_category(conn):
    bookmark = db.create_bookmark(conn, "juan", "reading", "Blog", "https://blog.dev")
    db.update_bookmark(conn, "juan", bookmark["id"], "  TOOLS  ", "Blog", "https://blog.dev")
    assert db.list_categories(conn, "juan") == ["tools"]


def test_rename_category_renames_all_its_bookmarks():
    conn = db.open_connection(":memory:")
    conn.executescript(db.SCHEMA)
    db.create_bookmark(conn, "juan", "apps", "A", "https://a.dev")
    db.create_bookmark(conn, "juan", "apps", "B", "https://b.dev")
    db.create_bookmark(conn, "juan", "sports", "C", "https://c.dev")

    assert db.rename_category(conn, "juan", "apps", "  Tools  ") is True
    grouped = db.list_bookmarks_grouped_by_category(conn, "juan")
    assert list(grouped.keys()) == ["tools", "sports"]
    assert [bm["name"] for bm in grouped["tools"]] == ["A", "B"]


def test_rename_category_preserves_order_position():
    conn = db.open_connection(":memory:")
    conn.executescript(db.SCHEMA)
    db.create_bookmark(conn, "juan", "apps", "A", "https://a.dev")
    db.create_bookmark(conn, "juan", "sports", "B", "https://b.dev")
    db.create_bookmark(conn, "juan", "youtube", "C", "https://c.dev")

    db.rename_category(conn, "juan", "sports", "games")
    assert list(db.list_bookmarks_grouped_by_category(conn, "juan").keys()) == ["apps", "games", "youtube"]


def test_rename_category_merges_into_existing_category():
    conn = db.open_connection(":memory:")
    conn.executescript(db.SCHEMA)
    db.create_bookmark(conn, "juan", "apps", "A", "https://a.dev")
    db.create_bookmark(conn, "juan", "tools", "B", "https://b.dev")

    assert db.rename_category(conn, "juan", "apps", "tools") is True
    grouped = db.list_bookmarks_grouped_by_category(conn, "juan")
    assert list(grouped.keys()) == ["tools"]
    assert [bm["name"] for bm in grouped["tools"]] == ["B", "A"]


def test_rename_category_is_noop_for_missing_or_unchanged_category(conn):
    db.create_bookmark(conn, "juan", "apps", "A", "https://a.dev")
    assert db.rename_category(conn, "juan", "ghost", "tools") is False
    assert db.rename_category(conn, "juan", "apps", "  APPS  ") is False
    assert db.list_categories(conn, "juan") == ["apps"]


def test_delete_category_removes_its_bookmarks_and_leaves_others_untouched(conn):
    db.create_bookmark(conn, "juan", "apps", "A", "https://a.dev")
    db.create_bookmark(conn, "juan", "apps", "B", "https://b.dev")
    db.create_bookmark(conn, "juan", "sports", "C", "https://c.dev")

    assert db.delete_category(conn, "juan", "apps") == 2
    assert db.list_categories(conn, "juan") == ["sports"]
    assert [bm["name"] for bm in db.list_bookmarks(conn, "juan")] == ["C"]


def test_delete_category_is_scoped_per_owner(conn):
    db.create_bookmark(conn, "juan", "apps", "A", "https://a.dev")
    db.create_bookmark(conn, "other", "apps", "B", "https://b.dev")

    assert db.delete_category(conn, "juan", "apps") == 1
    assert db.list_categories(conn, "juan") == []
    assert db.list_categories(conn, "other") == ["apps"]


def test_birthdays_crud_and_scoping(conn):
    birthday = db.create_birthday(conn, "juan", "Alex", 6, 1)
    assert birthday["month"] == 6
    assert birthday["day"] == 1
    assert [b["title"] for b in db.list_birthdays(conn, "juan")] == ["Alex"]
    assert db.list_birthdays(conn, "other") == []
    assert db.delete_birthday(conn, "other", birthday["id"]) is False
    assert db.delete_birthday(conn, "juan", birthday["id"]) is True
    assert db.list_birthdays(conn, "juan") == []


def test_vacations_crud_and_scoping(conn):
    vacation = db.create_vacation(conn, "juan", "Trip", "2026-08-01", "2026-08-10")
    assert vacation["start_date"] == "2026-08-01"
    assert [v["title"] for v in db.list_vacations(conn, "juan")] == ["Trip"]
    assert db.list_vacations(conn, "other") == []
    assert db.delete_vacation(conn, "other", vacation["id"]) is False
    assert db.delete_vacation(conn, "juan", vacation["id"]) is True
    assert db.list_vacations(conn, "juan") == []


def test_holidays_crud_and_scoping(conn):
    holiday = db.create_holiday(conn, "juan", "Andalucía", 2, 28)
    assert holiday["month"] == 2
    assert holiday["day"] == 28
    assert [h["title"] for h in db.list_holidays(conn, "juan")] == ["Andalucía"]
    assert db.list_holidays(conn, "other") == []
    assert db.get_holiday(conn, "other", holiday["id"]) is None
    assert db.delete_holiday(conn, "other", holiday["id"]) is False
    assert db.delete_holiday(conn, "juan", holiday["id"]) is True
    assert db.list_holidays(conn, "juan") == []


def test_getters_for_undo_return_none_when_not_owner(conn):
    bookmark = db.create_bookmark(conn, "juan", "reading", "Blog", "https://blog.dev")
    birthday = db.create_birthday(conn, "juan", "Alex", 6, 1)
    vacation = db.create_vacation(conn, "juan", "Trip", "2026-08-01", "2026-08-10")

    assert db.get_bookmark(conn, "juan", bookmark["id"])["name"] == "Blog"
    assert db.get_bookmark(conn, "other", bookmark["id"]) is None
    assert db.get_birthday(conn, "juan", birthday["id"])["title"] == "Alex"
    assert db.get_birthday(conn, "other", birthday["id"]) is None
    assert db.get_vacation(conn, "juan", vacation["id"])["title"] == "Trip"
    assert db.get_vacation(conn, "other", vacation["id"]) is None


def test_work_shift_upsert_and_scoping(conn):
    assert db.get_work_shift(conn, "juan") is None
    db.set_work_shift(conn, "juan", "2026-01-01", enabled=True)
    row = db.get_work_shift(conn, "juan")
    assert row["start_date"] == "2026-01-01"
    assert row["enabled"] == 1
    db.set_work_shift(conn, "juan", "2026-02-01", enabled=False)
    row = db.get_work_shift(conn, "juan")
    assert row["start_date"] == "2026-02-01"
    assert row["enabled"] == 0
    assert db.get_work_shift(conn, "other") is None


def test_shift_block_upsert_list_and_delete(conn):
    assert db.list_shift_blocks(conn, "juan") == []
    db.set_shift_block(conn, "juan", "2026-08-24", "morning")
    blocks = db.list_shift_blocks(conn, "juan")
    assert len(blocks) == 1
    assert blocks[0]["block_start"] == "2026-08-24"
    assert blocks[0]["shift_type"] == "morning"

    db.set_shift_block(conn, "juan", "2026-08-24", "night")
    blocks = db.list_shift_blocks(conn, "juan")
    assert len(blocks) == 1
    assert blocks[0]["shift_type"] == "night"

    assert db.list_shift_blocks(conn, "other") == []

    assert db.delete_shift_block(conn, "juan", "2026-08-24") is True
    assert db.list_shift_blocks(conn, "juan") == []
    assert db.delete_shift_block(conn, "juan", "2026-08-24") is False
