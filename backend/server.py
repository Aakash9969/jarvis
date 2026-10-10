"""
Local HTTP server for JARVIS.

Only standard-library modules are used, so the backend starts on a bare Python
install. It binds to 127.0.0.1 by default and serves both the static frontend
and the JSON API the UI talks to.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import posixpath
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import config
from .agent import Agent

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

MAX_BODY = 1_000_000

_agent: Agent | None = None
_agent_lock = threading.Lock()


def get_agent() -> Agent:
    global _agent
    with _agent_lock:
        if _agent is None:
            _agent = Agent()
        return _agent


class JarvisHandler(BaseHTTPRequestHandler):
    server_version = "JARVIS/1.0"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def log_message(self, fmt: str, *args) -> None:  # keep the console readable
        if "/api/" in (self.path or ""):
            return
        super().log_message(fmt, *args)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0 or length > MAX_BODY:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _serve_file(self, relative: str) -> None:
        # Resolve inside web/ only - no path traversal.
        relative = unquote(relative).replace("\\", "/").lstrip("/")
        safe = posixpath.normpath(relative)
        if safe.startswith("../") or safe in ("..", ""):
            safe = "index.html"

        target = (config.WEB_DIR / safe).resolve()
        try:
            target.relative_to(config.WEB_DIR.resolve())
        except ValueError:
            self._send_json({"error": "not found"}, 404)
            return

        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            self._send_json({"error": f"{safe} was not found"}, 404)
            return

        content_type, _ = mimetypes.guess_type(str(target))
        if target.suffix == ".js":
            content_type = "text/javascript"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type or 'application/octet-stream'}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------ #
    # routes
    # ------------------------------------------------------------------ #
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        agent = get_agent()

        if path == "/api/status":
            self._send_json(agent.status())
            return
        if path == "/api/verify":
            self._send_json(get_agent().llm.verify())
            return
        if path == "/api/models":
            self._send_json(get_agent().get_models())
            return
        if path == "/api/history":
            self._send_json({"history": agent.history(), "pending": agent.pending()})
            return
        if path == "/api/pending":
            self._send_json({"pending": agent.pending()})
            return
        if path.startswith("/api/"):
            self._send_json({"error": "unknown endpoint"}, 404)
            return

        self._serve_file(path if path != "/" else "/index.html")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        agent = get_agent()

        if path == "/api/command":
            payload = self._read_json()
            text = str(payload.get("text", ""))
            try:
                self._send_json(agent.handle(text))
            except Exception as exc:  # noqa: BLE001 - the UI must never see a crash
                self._send_json(
                    {
                        "ok": False,
                        "reply": f"Something went wrong inside me: {exc}",
                        "state": "error",
                        "intent": "ERROR",
                    },
                    200,
                )
            return

        if path == "/api/confirm":
            payload = self._read_json()
            pending_id = str(payload.get("id", ""))
            approve = bool(payload.get("approve"))
            try:
                self._send_json(agent.confirm(pending_id, approve))
            except Exception as exc:  # noqa: BLE001
                self._send_json({"ok": False, "reply": f"That did not work: {exc}", "state": "error"}, 200)
            return

        if path == "/api/reset":
            self._send_json(agent.reset())
            return

        if path == "/api/model":
            payload = self._read_json()
            model = str(payload.get("model", "")).strip()
            if not model:
                self._send_json({"ok": False, "error": "No model specified"}, 400)
                return
            self._send_json(agent.set_model(model))
            return

        if path == "/api/tts":
            if not EDGE_TTS_AVAILABLE:
                self._send_json({"ok": False, "error": "edge-tts not installed"}, 500)
                return
            payload = self._read_json()
            text = str(payload.get("text", "")).strip()
            voice = str(payload.get("voice", "en-US-GuyNeural")).strip()
            if not text:
                self._send_json({"ok": False, "error": "No text provided"}, 400)
                return
            try:
                audio_data = self._generate_tts(text, voice)
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Content-Length", str(len(audio_data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(audio_data)
            except Exception as exc:
                self._send_json({"ok": False, "error": f"TTS failed: {exc}"}, 500)
            return

        self._send_json({"error": "unknown endpoint"}, 404)

    def _generate_tts(self, text: str, voice: str) -> bytes:
        """Generate speech using edge-tts (Microsoft neural voices)."""
        async def _generate():
            communicate = edge_tts.Communicate(text, voice)
            audio_chunks = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_chunks.append(chunk["data"])
            return b"".join(audio_chunks)

        return asyncio.run(_generate())


def serve(host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    host = host or config.HOST
    port = port or config.PORT
    httpd = ThreadingHTTPServer((host, port), JarvisHandler)
    httpd.daemon_threads = True
    return httpd


def run_blocking(host: str | None = None, port: int | None = None) -> None:
    httpd = serve(host, port)
    print(f"JARVIS backend listening on http://{host or config.HOST}:{port or config.PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down JARVIS.")
    finally:
        httpd.server_close()
