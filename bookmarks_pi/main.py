"""FastAPI app: passwordless login via Telegram + bookmark CRUD, one process,
one SQLite file. No JS -- forms post back to the server and pages re-render.
"""
import sqlite3
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
def bookmarks_page(request: Request, conn=Depends(get_db)):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    birthdays = db.list_birthdays(conn, username)
    vacations = db.list_vacations(conn, username)
    shift_start = db.get_work_shift_start(conn, username)
    return render(
        request,
        "bookmarks.html",
        username=username,
        bookmarks_by_category=db.list_bookmarks_grouped_by_category(conn, username),
        categories=db.list_categories(conn, username),
        calendar_months=calendar_service.build_calendar_months(
            date.today(), NUM_CALENDAR_MONTHS, birthdays, vacations, shift_start
        ),
        birthdays=birthdays,
        vacations=vacations,
        shift_start=shift_start,
        error=None,
    )


@app.post("/calendar/birthdays")
def add_birthday(request: Request, title: str = Form(...), day: int = Form(...), month: int = Form(...), conn=Depends(get_db)):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    db.create_birthday(conn, username, title, month, day)
    return RedirectResponse("/bookmarks", status_code=303)


@app.post("/calendar/birthdays/{birthday_id}/delete")
def delete_birthday(request: Request, birthday_id: int, conn=Depends(get_db)):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    db.delete_birthday(conn, username, birthday_id)
    return RedirectResponse("/bookmarks", status_code=303)


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
    return RedirectResponse("/bookmarks", status_code=303)


@app.post("/calendar/vacations/{vacation_id}/delete")
def delete_vacation(request: Request, vacation_id: int, conn=Depends(get_db)):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    db.delete_vacation(conn, username, vacation_id)
    return RedirectResponse("/bookmarks", status_code=303)


@app.post("/calendar/shift")
def set_shift(request: Request, start_date: str = Form(...), conn=Depends(get_db)):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    db.set_work_shift_start(conn, username, start_date)
    return RedirectResponse("/bookmarks", status_code=303)


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
    return RedirectResponse("/bookmarks", status_code=303)


@app.post("/bookmarks/{bookmark_id}/delete")
def delete_bookmark(request: Request, bookmark_id: int, conn=Depends(get_db)):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    db.delete_bookmark(conn, username, bookmark_id)
    return RedirectResponse("/bookmarks", status_code=303)
