import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from bot import TierBot


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"MCPE Tier Bot is online")

    def log_message(self, format, *args):
        pass


def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


def main():
    threading.Thread(
        target=start_health_server,
        daemon=True
    ).start()

    bot = TierBot()
    bot.run()


if __name__ == "__main__":
    main()
