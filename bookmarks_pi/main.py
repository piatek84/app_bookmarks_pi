"""FastAPI app: passwordless login via Telegram + bookmark CRUD, one process,
one SQLite file. No JS -- forms post back to the server and pages re-render.
"""
import sqlite3
from pathlib import Path
from typing import Iterator, Optional

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.middleware.sessions import SessionMiddleware

from . import db, telegram
from .config import load_settings

settings = load_settings()
db.init_db(settings.database_path)

BASE_DIR = Path(__file__).resolve().parent
jinja_env = Environment(
    loader=FileSystemLoader(BASE_DIR / "templates"),
    autoescape=select_autoescape(["html"]),
)

app = FastAPI(title="bookmarks-pi")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)


def render(name: str, status_code: int = 200, **context) -> HTMLResponse:
    html = jinja_env.get_template(name).render(**context)
    return HTMLResponse(html, status_code=status_code)


def get_db() -> Iterator[sqlite3.Connection]:
    conn = db.open_connection(settings.database_path)
    try:
        yield conn
    finally:
        conn.close()


def _current_username(request: Request) -> Optional[str]:
    return request.session.get("username")


@app.get("/")
def index(request: Request):
    if _current_username(request):
        return RedirectResponse("/bookmarks", status_code=303)
    return render("login.html", error=None)


@app.post("/login")
def login(username: str = Form(...), conn=Depends(get_db)):
    user = db.get_user(conn, username)
    if user is None:
        return render("login.html", status_code=404, error=f'Unknown user "{username}"')
    code = db.create_login_code(conn, username, settings.login_code_ttl_seconds, settings.login_code_length)
    telegram.send_message(settings.telegram_bot_token, user["telegram_chat_id"], f"Your bookmarks login code: {code}")
    return render("verify.html", username=username, error=None)


@app.post("/verify")
def verify(request: Request, username: str = Form(...), code: str = Form(...), conn=Depends(get_db)):
    if not db.verify_login_code(conn, username, code):
        return render("verify.html", status_code=401, username=username, error="Invalid or expired code")
    request.session["username"] = username
    return RedirectResponse("/bookmarks", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/bookmarks")
def bookmarks_page(request: Request, category: Optional[str] = None, conn=Depends(get_db)):
    username = _current_username(request)
    if not username:
        return RedirectResponse("/", status_code=303)
    return render(
        "bookmarks.html",
        username=username,
        bookmarks=db.list_bookmarks(conn, username, category),
        categories=db.list_categories(conn, username),
        category_filter=category or "",
        error=None,
    )


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
