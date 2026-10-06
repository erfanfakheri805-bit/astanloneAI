"""
Interface System
==================
Serves the modern chat UI (static/) and a small JSON API on top of Core,
using only the Python standard library (http.server) so the application
has zero third-party runtime dependencies and no internet access is
required to run it.

Endpoints:
    GET  /                    -> index.html
    GET  /static/*            -> static assets (css/js), path-traversal safe
    POST /api/message         -> {text} -> {reply, status}
    GET  /api/status          -> developer panel data (real, computed health)
    GET  /api/history         -> recent conversation log
    GET  /api/health          -> full component-by-component health check
    GET  /api/learning-history -> recent learning_events rows
    GET  /api/errors          -> recent error_log rows
    GET  /api/runtime-result  -> runtime-integration result of the last message
    POST /api/inspect-code    -> {code} -> AST-based structural analysis
    POST /api/runtime-growth  -> {kind, goal, target, ...} -> controlled runtime-growth
                                 result (Prompt 954: delegates to the existing
                                 RuntimeCore.run_controlled_runtime_growth(); in-memory,
                                 not persistent, not permission/authorization)

Security notes (see the master project's Section 19):
    - `/static/*` resolves the requested path with os.path.realpath and
      verifies it is still inside STATIC_DIR before serving anything,
      closing a path-traversal hole that existed in the 0.1.0 build
      (a request like `/static/../../skills/definitions/greet.json`
      could previously escape the static directory for any file whose
      extension happened to be one of the allowed content types).
    - POST bodies are capped at MAX_BODY_BYTES to bound memory use
      against a request that lies about (or abuses) Content-Length.
    - Unexpected exceptions are caught, logged to the real error_log
      via Core's memory system, and answered with a generic message -
      the server never leaks a stack trace to the client, and never
      silently swallows the failure either.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.core import Core
from core.config import UIConfig
from runtime_integration.runtime_core import RuntimeCore

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
_STATIC_ROOT = os.path.realpath(STATIC_DIR)

MAX_BODY_BYTES = 1_000_000  # 1 MB - generous for chat/AEL/code payloads, bounded against abuse.
DRAIN_HARD_CAP = 20_000_000  # never read more than this many bytes when draining a rejected body.

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


def _safe_static_path(rel):
    """Resolve a requested static-file path and make sure it cannot
    escape STATIC_DIR via '..', an absolute path, or a null byte.
    Returns the resolved real path if safe, or None otherwise."""
    if not rel or "\x00" in rel:
        return None
    candidate = os.path.realpath(os.path.join(STATIC_DIR, rel))
    if candidate == _STATIC_ROOT or candidate.startswith(_STATIC_ROOT + os.sep):
        return candidate
    return None


def make_handler(core: Core):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # keep the console quiet; the UI is the primary surface

        # ------------------------------------------------------------
        def _send_json(self, payload, status=200):
            body = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path, content_type):
            with open(path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _log_server_error(self, operation, exc):
            try:
                core.log_error(operation, str(exc))
            except Exception:
                pass  # diagnostics must never crash the request handler

        # ------------------------------------------------------------
        def do_GET(self):
            try:
                self._route_get()
            except Exception as e:
                self._log_server_error(f"GET {self.path}", e)
                self._send_json({"error": "internal server error"}, 500)

        def _route_get(self):
            path = self.path.split("?", 1)[0]

            if path in ("/", "/index.html"):
                return self._send_file(os.path.join(STATIC_DIR, "index.html"), CONTENT_TYPES[".html"])

            if path.startswith("/static/"):
                rel = path[len("/static/"):]
                full_path = _safe_static_path(rel)
                ext = os.path.splitext(full_path)[1] if full_path else ""
                if full_path and os.path.isfile(full_path) and ext in CONTENT_TYPES:
                    return self._send_file(full_path, CONTENT_TYPES[ext])
                return self._send_json({"error": "not found"}, 404)

            if path == "/api/status":
                return self._send_json(core.status_snapshot())

            if path == "/api/history":
                return self._send_json({"messages": core.recent_messages(50)})

            if path == "/api/health":
                return self._send_json(core.health.check())

            if path == "/api/learning-history":
                return self._send_json({"events": core.recent_learning_events(50)})

            if path == "/api/errors":
                return self._send_json({"errors": core.recent_errors(50)})

            if path == "/api/runtime-result":
                # Prompt 910: read-only view of the runtime-integration result
                # for the most recent message (None before the first one).
                getter = getattr(core, "get_last_runtime_result", None)  # RuntimeCore only
                return self._send_json({"runtime_result": getter() if getter else None})

            return self._send_json({"error": "not found"}, 404)

        def do_POST(self):
            try:
                self._route_post()
            except Exception as e:
                self._log_server_error(f"POST {self.path}", e)
                self._send_json({"error": "internal server error"}, 500)

        def _drain(self, n):
            """Reads and discards up to n bytes from the request body.
            Used before rejecting an oversized request so the client's
            in-flight write() completes normally instead of racing a
            connection reset the moment we respond and move on."""
            remaining = n
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)

        def _read_json_body(self):
            """Returns (data, error_response_or_None). On error, the caller
            should return immediately - the error response has already been
            sent to the client."""
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                self._send_json({"error": "invalid Content-Length"}, 400)
                return None, True
            if length > MAX_BODY_BYTES:
                self._drain(min(length, DRAIN_HARD_CAP))
                self._send_json({"error": "request body too large"}, 413)
                return None, True
            raw = self.rfile.read(length) if length else b"{}"
            try:
                return json.loads(raw.decode("utf-8")), None
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json({"error": "invalid json"}, 400)
                return None, True

        def _route_post(self):
            path = self.path.split("?", 1)[0]

            if path == "/api/message":
                data, errored = self._read_json_body()
                if errored:
                    return
                text = data.get("text", "") if isinstance(data, dict) else ""
                reply = core.process_input(text)
                return self._send_json({"reply": reply, "status": core.status_snapshot()})

            if path == "/api/inspect-code":
                data, errored = self._read_json_body()
                if errored:
                    return
                code = data.get("code", "") if isinstance(data, dict) else ""
                if not isinstance(code, str):
                    return self._send_json({"error": "'code' must be a string"}, 400)
                return self._send_json(core.inspect_code(code))

            if path == "/api/runtime-growth":
                # Prompt 954: controlled growth entry. Only hands the parsed body to the
                # existing RuntimeCore (the one this handler already serves); the result
                # is returned unchanged. A plain Core has no such method -> not found.
                grow = getattr(core, "run_controlled_runtime_growth", None)
                if grow is None:
                    return self._send_json({"error": "not found"}, 404)
                data, errored = self._read_json_body()
                if errored:
                    return
                return self._send_json(grow(data))

            return self._send_json({"error": "not found"}, 404)

    return Handler


def run(host=None, port=None):
    ui_config = UIConfig()
    host = host or ui_config.host
    port = port or ui_config.port
    core = RuntimeCore()
    handler_cls = make_handler(core)
    server = ThreadingHTTPServer((host, port), handler_cls)
    print(f"Standalone AI application running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    run()
