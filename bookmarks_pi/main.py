"""FastAPI app: passwordless login via Telegram + bookmark CRUD, one process,
one SQLite file. No JS -- forms post back to the server and pages re-render.
"""
import re
import sqlite3
import urllib.parse
from datetime import date
from pathlib import Path
from typing import Iterator, Optional

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.middleware.sessions import SessionMiddleware

from . import calendar_service, db, telegram
from .config import load_settings

settings = load_settings()
db.init_db(settings.database_path)

NUM_CALENDAR_MONTHS = 3

BASE_DIR = Path(__file__).resolve().parent
jinja_env = Environment(
    loader=FileSystemLoader(BASE_DIR / "templates"),
    autoescape=select_autoescape(["html"]),
)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-") or "category"


jinja_env.filters["slugify"] = slugify

app = FastAPI(title="bookmarks-pi")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)


def render(request: Request, name: str, status_code: int = 200, **context) -> HTMLResponse:
    html = jinja_env.get_template(name).render(theme=_current_theme(request), **context)
    return HTMLResponse(html, status_code=status_code)


def get_db() -> Iterator[sqlite3.Connection]:
    conn = db.open_connection(settings.database_path)
    try:
        yield conn
    finally:
        conn.close()


def _current_username(request: Request) -> Optional[str]:
    return request.session.get("username")


def _current_theme(request: Request) -> str:
    return request.session.get("theme", "dark")


def _redirect_to_bookmarks(fragment: Optional[str] = None, **params) -> RedirectResponse:
    clean = {k: v for k, v in params.items() if v is not None}
    query = urllib.parse.urlencode(clean)
    url = "/bookmarks" + (f"?{query}" if query else "")
    if fragment:
        url += f"#{fragment}"
    return RedirectResponse(url, status_code=303)


def _build_undo_context(
    undo: Optional[str],
    title: Optional[str],
    month: Optional[int],
    day: Optional[int],
    start_date: Optional[str],
    end_date: Optional[str],
    category: Optional[str],
    name: Optional[str],
    url: Optional[str],
) -> Optional[dict]:
    if undo == "birthday" and None not in (title, month, day):
        return {"label": f'birthday "{title}"', "action": "/calendar/birthdays/restore", "fields": {"title": title, "month": month, "day": day}}
    if undo == "holiday" and None not in (title, month, day):
        return {"label": f'holiday "{title}"', "action": "/calendar/holidays/restore", "fields": {"title": title, "month": month, "day": day}}
    if undo == "vacation" and None not in (title, start_date, end_date):
        return {"label": f'vacation "{title}"', "action": "/calendar/vacations/restore", "fields": {"title": title, "start_date": start_date, "end_date": end_date}}
    if undo == "bookmark" and None not in (category, name, url):
        return {"label": f'bookmark "{name}"', "action": "/bookmarks/restore", "fields": {"category": category, "name": name, "url": url}}
    return None


@app.get("/")
def index(request: Request):
    if _current_username(request):
        return RedirectResponse("/bookmarks", status_code=303)
    return render(request, "login.html", error=None)


@app.post("/login")
def login(request: Request, username: str = Form(...), conn=Depends(get_db)):
    user = db.get_user(conn, username)
    if user is None:
        return render(request, "login.html", status_code=404, error=f'Unknown user "{username}"')
    code = db.create_login_code(conn, username, settings.login_code_ttl_seconds, settings.login_code_length)
    telegram.send_message(settings.telegram_bot_token, user["telegram_chat_id"], f"Your bookmarks login code: {code}")
    return render(request, "verify.html", username=username, error=None)


@app.post("/verify")
def verify(request: Request, username: str = Form(...), code: str = Form(...), conn=Depends(get_db)):
    if not db.verify_login_code(conn, username, code):
        return render(request, "verify.html", status_code=401, username=username, error="Invalid or expired code")
    request.session["username"] = username
    return RedirectResponse("/bookmarks", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.post("/theme")
def toggle_theme(request: Request):
    request.session["theme"] = "light" if _current_theme(request) == "dark" else "dark"
    destination = "/bookmarks" if _current_username(request) else "/"
    return RedirectResponse(destination, status_code=303)


@app.get("/bookmarks")
def bookmarks_page(
    request: Request,
    conn=Depends(get_db),
    open_manage: Optional[str] = None,
    open_bookmarks: Optional[str] = None,
    open_more: Optional[str] = None,
    undo: Optional[str] = None,
    title: Optional[str] = None,
    month: Optional[int] = None,
    day: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    name: Optional[str] = None,
    url: Optional[str] = None,
):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    birthdays = db.list_birthdays(conn, username)
    vacations = db.list_vacations(conn, username)
    holidays = db.list_holidays(conn, username)
    shift_start = db.get_work_shift_start(conn, username)
    return render(
        request,
        "bookmarks.html",
        username=username,
        bookmarks_by_category=db.list_bookmarks_grouped_by_category(conn, username),
        categories=db.list_categories(conn, username),
        calendar_months=calendar_service.build_calendar_months(
            date.today(), NUM_CALENDAR_MONTHS, birthdays, vacations, shift_start, holidays
        ),
        birthdays=birthdays,
        vacations=vacations,
        holidays=holidays,
        shift_start=shift_start,
        open_manage=bool(open_manage),
        open_bookmarks=bool(open_bookmarks),
        open_more_category=open_more,
        undo=_build_undo_context(undo, title, month, day, start_date, end_date, category, name, url),
        error=None,
    )


@app.post("/calendar/birthdays")
def add_birthday(request: Request, title: str = Form(...), day: int = Form(...), month: int = Form(...), conn=Depends(get_db)):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    db.create_birthday(conn, username, title, month, day)
    return _redirect_to_bookmarks(open_manage=1, fragment="calendar-settings")


@app.post("/calendar/birthdays/{birthday_id}/delete")
def delete_birthday(request: Request, birthday_id: int, conn=Depends(get_db)):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    row = db.get_birthday(conn, username, birthday_id)
    if row is None:
        return _redirect_to_bookmarks(open_manage=1, fragment="calendar-settings")
    db.delete_birthday(conn, username, birthday_id)
    return _redirect_to_bookmarks(
        open_manage=1, undo="birthday", title=row["title"], month=row["month"], day=row["day"], fragment="calendar-settings"
    )


@app.post("/calendar/birthdays/restore")
def restore_birthday(request: Request, title: str = Form(...), month: int = Form(...), day: int = Form(...), conn=Depends(get_db)):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    db.create_birthday(conn, username, title, month, day)
    return _redirect_to_bookmarks(open_manage=1, fragment="calendar-settings")


@app.post("/calendar/holidays")
def add_holiday(request: Request, title: str = Form(...), day: int = Form(...), month: int = Form(...), conn=Depends(get_db)):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    db.create_holiday(conn, username, title, month, day)
    return _redirect_to_bookmarks(open_manage=1, fragment="calendar-settings")


@app.post("/calendar/holidays/{holiday_id}/delete")
def delete_holiday(request: Request, holiday_id: int, conn=Depends(get_db)):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    row = db.get_holiday(conn, username, holiday_id)
    if row is None:
        return _redirect_to_bookmarks(open_manage=1, fragment="calendar-settings")
    db.delete_holiday(conn, username, holiday_id)
    return _redirect_to_bookmarks(
        open_manage=1, undo="holiday", title=row["title"], month=row["month"], day=row["day"], fragment="calendar-settings"
    )


@app.post("/calendar/holidays/restore")
def restore_holiday(request: Request, title: str = Form(...), month: int = Form(...), day: int = Form(...), conn=Depends(get_db)):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    db.create_holiday(conn, username, title, month, day)
    return _redirect_to_bookmarks(open_manage=1, fragment="calendar-settings")


@app.post("/calendar/vacations")
def add_vacation(
    request: Request,
    title: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    conn=Depends(get_db),
):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    db.create_vacation(conn, username, title, start_date, end_date)
    return _redirect_to_bookmarks(open_manage=1, fragment="calendar-settings")


@app.post("/calendar/vacations/{vacation_id}/delete")
def delete_vacation(request: Request, vacation_id: int, conn=Depends(get_db)):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    row = db.get_vacation(conn, username, vacation_id)
    if row is None:
        return _redirect_to_bookmarks(open_manage=1, fragment="calendar-settings")
    db.delete_vacation(conn, username, vacation_id)
    return _redirect_to_bookmarks(
        open_manage=1,
        undo="vacation",
        title=row["title"],
        start_date=row["start_date"],
        end_date=row["end_date"],
        fragment="calendar-settings",
    )


@app.post("/calendar/vacations/restore")
def restore_vacation(
    request: Request,
    title: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    conn=Depends(get_db),
):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    db.create_vacation(conn, username, title, start_date, end_date)
    return _redirect_to_bookmarks(open_manage=1, fragment="calendar-settings")


@app.post("/calendar/shift")
def set_shift(request: Request, start_date: str = Form(...), conn=Depends(get_db)):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    db.set_work_shift_start(conn, username, start_date)
    return _redirect_to_bookmarks(open_manage=1, fragment="calendar-settings")


@app.post("/bookmarks")
def add_bookmark(
    request: Request,
    category: str = Form(...),
    name: str = Form(...),
    url: str = Form(...),
    conn=Depends(get_db),
):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    db.create_bookmark(conn, username, category, name, url)
    return _redirect_to_bookmarks(open_bookmarks=1, fragment="bookmarks-settings")


@app.post("/bookmarks/{bookmark_id}/edit")
def edit_bookmark(
    request: Request,
    bookmark_id: int,
    category: str = Form(...),
    name: str = Form(...),
    url: str = Form(...),
    open_more: Optional[str] = Form(None),
    conn=Depends(get_db),
):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    db.update_bookmark(conn, username, bookmark_id, category, name, url)
    return _redirect_to_bookmarks(
        fragment=f"category-{slugify(category)}", open_more=category if open_more else None
    )


@app.post("/bookmarks/{bookmark_id}/delete")
def delete_bookmark(request: Request, bookmark_id: int, open_more: Optional[str] = Form(None), conn=Depends(get_db)):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    row = db.get_bookmark(conn, username, bookmark_id)
    if row is None:
        return _redirect_to_bookmarks()
    db.delete_bookmark(conn, username, bookmark_id)
    return _redirect_to_bookmarks(
        undo="bookmark",
        category=row["category"],
        name=row["name"],
        url=row["url"],
        fragment=f"category-{slugify(row['category'])}",
        open_more=row["category"] if open_more else None,
    )


@app.post("/bookmarks/restore")
def restore_bookmark(request: Request, category: str = Form(...), name: str = Form(...), url: str = Form(...), conn=Depends(get_db)):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    db.create_bookmark(conn, username, category, name, url)
    return _redirect_to_bookmarks(fragment=f"category-{slugify(category)}")


@app.post("/bookmarks/categories/move")
def move_category(
    request: Request,
    category: str = Form(...),
    direction: str = Form(...),
    open_more: Optional[str] = Form(None),
    conn=Depends(get_db),
):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    db.move_category(conn, username, category, -1 if direction == "up" else 1)
    return _redirect_to_bookmarks(
        fragment=f"category-{slugify(category)}", open_more=category if open_more else None
    )


@app.post("/bookmarks/categories/reorder")
def reorder_categories(request: Request, category: list[str] = Form(...), conn=Depends(get_db)):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    db.reorder_categories(conn, username, category)
    return _redirect_to_bookmarks()


@app.post("/bookmarks/reorder")
def reorder_bookmarks(
    request: Request,
    category: str = Form(...),
    id: list[int] = Form(...),
    open_more: Optional[str] = Form(None),
    conn=Depends(get_db),
):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    db.reorder_bookmarks(conn, username, category, id)
    return _redirect_to_bookmarks(
        fragment=f"category-{slugify(category)}", open_more=category if open_more else None
    )
