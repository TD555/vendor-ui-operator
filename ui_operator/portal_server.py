"""Serve the frozen mock portal on 127.0.0.1 in a background thread."""
from __future__ import annotations

import functools
import hashlib
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from .config import PORTAL_DIR, PORTAL_FILE, PORTAL_HOST, PORTAL_PORT


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep CLI output readable
        pass


class PortalServer:
    def __init__(self, host: str = PORTAL_HOST, port: int = PORTAL_PORT):
        handler = functools.partial(_QuietHandler, directory=str(PORTAL_DIR))
        self.httpd = ThreadingHTTPServer((host, port), handler)
        self.host, self.port = host, self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def origin(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def url(self) -> str:
        return f"{self.origin}/{PORTAL_FILE}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def portal_sha256() -> str:
    return hashlib.sha256((PORTAL_DIR / PORTAL_FILE).read_bytes()).hexdigest()
