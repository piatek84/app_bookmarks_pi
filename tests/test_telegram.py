import json

import httpx
import pytest
import respx

from bookmarks_pi import telegram


@respx.mock
def test_send_message_posts_to_telegram_api():
    route = respx.post("https://api.telegram.org/bottest-token/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    telegram.send_message("test-token", 12345, "your code: 123456")

    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body == {"chat_id": 12345, "text": "your code: 123456"}


@respx.mock
def test_send_message_raises_on_http_error():
    respx.post("https://api.telegram.org/bottest-token/sendMessage").mock(
        return_value=httpx.Response(400, json={"ok": False, "description": "bad request"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        telegram.send_message("test-token", 12345, "hi")
