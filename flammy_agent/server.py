"""Tiny stdlib HTTP/SSE bridge so any existing UI can consume Flammy without changes
to its design: it just fetches JSON or listens to an EventSource."""
from __future__ import annotations

import json
import queue
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_server(agent, host: str, port: int, cors: str = "*") -> ThreadingHTTPServer:
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):          # keep the host app's console clean
            pass

        def _head(self, code=200, ctype="application/json", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            if cors:
                self.send_header("Access-Control-Allow-Origin", cors)
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            for k, v in (extra or {}).items():
                self.send_header(k, v)

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self._head(code, extra={"Content-Length": str(len(body))})
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self._head(204, extra={"Content-Length": "0"})
            self.end_headers()

        def do_GET(self):
            path = self.path.split("?")[0].rstrip("/")
            if path == "/flammy/latest":
                a = agent.latest()
                self._json(a.to_dict() if a else None)
            elif path == "/flammy/pending":
                self._json([a.to_dict() for a in agent.pending()])
            elif path == "/flammy/history":
                self._json([a.to_dict() for a in agent.history(50)])
            elif path == "/flammy/stream":
                self._stream()
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            if self.path.split("?")[0].rstrip("/") != "/flammy/observe":
                return self._json({"error": "not found"}, 404)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n) or b"{}")
                a = agent.observe(data.pop("type", "manual"), **data)
                self._json(a.to_dict() if a else None)
            except Exception as e:
                self._json({"error": str(e)}, 400)

        def _stream(self):
            self._head(200, "text/event-stream", {"Cache-Control": "no-cache", "Connection": "keep-alive"})
            self.end_headers()
            q = agent.subscribe_queue()
            try:
                self.wfile.write(b": flammy connected\n\n")
                self.wfile.flush()
                while True:
                    try:
                        a = q.get(timeout=15)
                        self.wfile.write(b"event: advisory\ndata: " + json.dumps(a.to_dict(), ensure_ascii=False).encode() + b"\n\n")
                    except queue.Empty:
                        self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                agent.unsubscribe_queue(q)

    srv = ThreadingHTTPServer((host, port), H)
    srv.daemon_threads = True
    return srv
