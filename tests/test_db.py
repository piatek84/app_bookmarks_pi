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
