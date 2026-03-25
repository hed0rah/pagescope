"""Simple HTTP server for test fixture sites.

Usage:
    python tests/fixtures/serve.py [--port 8888]

Serves the HTML test pages from tests/fixtures/sites/.
"""

from __future__ import annotations

import argparse
import http.server
import os
import ssl
import threading
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "sites"


class TestHandler(http.server.SimpleHTTPRequestHandler):
    """Handler that serves test fixtures and simulates various error conditions."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FIXTURES_DIR), **kwargs)

    def do_GET(self):
        # simulate specific error responses
        if self.path.startswith("/api/"):
            self._handle_api()
            return

        # simulate slow responses
        if "slow" in self.path and self.path.endswith(".js"):
            import time
            time.sleep(2)  # 2 second delay

        # let the normal handler serve static files
        super().do_GET()

    def _handle_api(self):
        """Simulate various API failure modes."""
        if "nonexistent" in self.path:
            self.send_error(404, "API endpoint not found")
        elif "server-error" in self.path:
            self.send_error(500, "Internal server error")
        elif "unauthorized" in self.path:
            self.send_error(401, "Unauthorized")
        elif "forbidden" in self.path:
            self.send_error(403, "Forbidden")
        elif "rate-limit" in self.path:
            self.send_response(429)
            self.send_header("Retry-After", "60")
            self.end_headers()
            self.wfile.write(b'{"error": "rate limited"}')
        elif "rapid-fire" in self.path:
            self.send_error(404, "Not found")
        elif "unhandled" in self.path:
            self.send_error(500, "Unhandled server error")
        else:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')

    def log_message(self, format, *args):
        """Quieter logging."""
        pass


def start_server(port: int = 8888) -> http.server.HTTPServer:
    """Start the test fixture server. Returns the server instance."""
    server = http.server.HTTPServer(("127.0.0.1", port), TestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Test fixture server running at http://127.0.0.1:{port}")
    print(f"Serving files from {FIXTURES_DIR}")
    print(f"\nTest pages:")
    for f in sorted(FIXTURES_DIR.glob("*.html")):
        print(f"  http://127.0.0.1:{port}/{f.name}")
    return server


def main():
    parser = argparse.ArgumentParser(description="Serve test fixture sites")
    parser.add_argument("--port", type=int, default=8888, help="Port to listen on")
    args = parser.parse_args()

    server = start_server(args.port)
    try:
        print(f"\nPress Ctrl+C to stop")
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
