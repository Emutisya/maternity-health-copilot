"""Loopback-only HTTP inference; requests are never persisted or logged."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .core import BANNER, OPTIONS, retrieve


def make_server(model, port=8765):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, payload, content_type="application/json"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self):
            expected = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != expected:
                self.send(403, {"error": "Use the documented loopback URL.", "notice": BANNER})
                return False
            origin = self.headers.get("Origin")
            if origin is not None and origin != f"http://{expected}":
                self.send(403, {"error": "Cross-origin requests are not accepted.", "notice": BANNER})
                return False
            return True

        def do_GET(self):
            if not self.allowed():
                return
            path = urlsplit(self.path).path
            if path == "/":
                self.send(200, (Path(__file__).parent / "dashboard.html").read_bytes(),
                          "text/html; charset=utf-8")
            elif path == "/api/options":
                self.send(200, {"options": OPTIONS, "notice": BANNER, "synthetic": True})
            elif path == "/api/health":
                self.send(200, {"status": "ready", "scope": "synthetic educational retrieval"})
            else:
                self.send(404, {"error": "Not found.", "notice": BANNER})

        def do_POST(self):
            if not self.allowed():
                return
            if self.path != "/api/resources":
                self.send(404, {"error": "Not found.", "notice": BANNER})
                return
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                self.send(415, {"error": "Use application/json.", "notice": BANNER})
                return
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError("Transfer encoding is not accepted.")
                size = int(self.headers.get("Content-Length", "0"))
                if not 1 <= size <= 2048:
                    raise ValueError("Request size must be between 1 and 2048 bytes.")
                self.connection.settimeout(5)
                raw = self.rfile.read(size)
                payload = json.loads(raw)
                result = retrieve(model, payload)
            except (ValueError, UnicodeError, TimeoutError):
                self.send(400, {"error": "Invalid input. Only the documented bounded selections are accepted; no symptoms or personal data.", "notice": BANNER})
                return
            self.send(200, result)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
