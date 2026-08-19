import pytest

from bookmarks_pi import db


@pytest.fixture
def conn(tmp_path):
    database_path = str(tmp_path / "test.db")
    db.init_db(database_path)
    connection = db.open_connection(database_path)
    yield connection
    connection.close()


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
    assert [b["name"] for b in grouped["reading"]] == ["Feed", "Blog"]
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


def test_work_shift_start_upsert_and_scoping(conn):
    assert db.get_work_shift_start(conn, "juan") is None
    db.set_work_shift_start(conn, "juan", "2026-01-01")
    assert db.get_work_shift_start(conn, "juan") == "2026-01-01"
    db.set_work_shift_start(conn, "juan", "2026-02-01")
    assert db.get_work_shift_start(conn, "juan") == "2026-02-01"
    assert db.get_work_shift_start(conn, "other") is None
