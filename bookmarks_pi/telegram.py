"""Thin wrapper around the Telegram Bot API's sendMessage call.

The bot token never has a default and is always passed in explicitly (see
config.Settings.telegram_bot_token) -- it must never be hardcoded or committed.
"""
import httpx

API_BASE_URL = "https://api.telegram.org"


def send_message(bot_token: str, chat_id: int, text: str, *, api_base_url: str = API_BASE_URL) -> None:
    response = httpx.post(
        f"{api_base_url}/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=10,
    )
    response.raise_for_status()
