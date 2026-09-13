"""Container entrypoint: bind the HTTP health port before importing the bot."""
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


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


port = int(os.getenv("PORT", "8000"))
server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()
print(f"Early health server listening on 0.0.0.0:{port}", flush=True)

# Import only after the health endpoint is bound. This prevents a missing or
# invalid environment variable from causing a platform health-check failure.
import main  # noqa: E402

main.asyncio.run(main.main())
