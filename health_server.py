import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telethon import TelegramClient

HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", "8000"))


# Telethon cannot resolve a raw -100... channel ID unless the account has
# learned the channel's access hash. Search the logged-in user's dialogs as
# a fallback so private channels work when the user account has access.
_original_get_entity = TelegramClient.get_entity


def _numeric_peer_id(value):
    try:
        raw = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    text = str(raw)
    if text.startswith("-100"):
        return int(text[4:])
    return abs(raw)


async def _get_entity_with_numeric_fallback(self, entity):
    value = str(entity).strip() if entity is not None else ""
    if not re.fullmatch(r"-?\d+", value):
        return await _original_get_entity(self, entity)

    try:
        return await _original_get_entity(self, entity)
    except Exception as original_error:
        wanted = _numeric_peer_id(value)
        if wanted is None:
            raise

        async for dialog in self.iter_dialogs():
            candidate = dialog.entity
            if getattr(candidate, "id", None) == wanted:
                return candidate

        raise RuntimeError(
            f"Telegram chat {value} is not accessible to the logged-in user session. "
            "Make sure this user account is a member of the private channel and "
            "that the channel appears in the account's Telegram dialogs, then redeploy."
        ) from original_error


TelegramClient.get_entity = _get_entity_with_numeric_fallback


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Dhanu Telegram AutoFilter is running")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), HealthHandler)
    print(f"Health server listening on {HOST}:{PORT}")
    server.serve_forever()
