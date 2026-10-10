"""
LLM integration.

Speaks the OpenAI *chat completions* protocol, which is also implemented by
Azure-compatible gateways, Groq, OpenRouter, Ollama (``/v1``) and LM Studio.

Design rules:
* the API key is read from the environment and never leaves the backend;
* a network/auth failure degrades gracefully to the offline brain instead of
  crashing the request;
* failures are cached for a short cooldown so we do not pay a timeout on every
  single message.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

from . import config

COOLDOWN_SECONDS = 90


class LLM:
    def __init__(self) -> None:
        self.model = config.LLM_MODEL
        self.base_url = config.LLM_BASE_URL
        self.timeout = config.LLM_TIMEOUT
        self._lock = threading.Lock()
        self._fail_until = 0.0
        self.last_error: str | None = None
        self.last_ok: float | None = None

    # ------------------------------------------------------------------ #
    # status
    # ------------------------------------------------------------------ #
    @property
    def configured(self) -> bool:
        return bool(config.LLM_API_KEY) and config.LLM_ENABLED

    @property
    def cooling_down(self) -> bool:
        return time.time() < self._fail_until

    def available(self) -> bool:
        return self.configured and not self.cooling_down

    def status(self) -> dict:
        if not config.LLM_ENABLED:
            state = "disabled"
        elif not config.LLM_API_KEY:
            state = "unconfigured"
        elif self.cooling_down:
            state = "error"
        elif self.last_ok:
            state = "online"
        else:
            state = "ready"
        return {
            "state": state,
            "model": self.model,
            "base_url": self.base_url,
            "last_error": self.last_error,
            "last_ok": self.last_ok,
        }

    def _note_failure(self, message: str) -> None:
        with self._lock:
            self.last_error = message
            self._fail_until = time.time() + COOLDOWN_SECONDS

    # ------------------------------------------------------------------ #
    # request
    # ------------------------------------------------------------------ #
    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        temperature: float = 0.5,
        max_tokens: int = 900,
    ) -> dict:
        """
        Call the model.

        Returns ``{"ok": bool, "message": {...}, "error": str|None}``.
        """
        if not self.available():
            return {"ok": False, "message": None, "error": self.last_error or "LLM not available"}

        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.LLM_API_KEY}",
                "User-Agent": "JARVIS-Desktop/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                body = json.loads(exc.read().decode("utf-8", errors="replace"))
                detail = body.get("error", {}).get("message", "")
            except Exception:  # noqa: BLE001
                pass
            if exc.code == 401:
                message = "The configured AI key was rejected (401 Unauthorized)."
            elif exc.code == 404:
                message = f"The model \"{self.model}\" was not found at {self.base_url}."
            elif exc.code == 429:
                message = "The AI provider is rate limiting requests (429)."
            else:
                message = f"AI request failed with HTTP {exc.code}. {detail}".strip()
            self._note_failure(message)
            return {"ok": False, "message": None, "error": message}
        except urllib.error.URLError as exc:
            message = f"I could not reach the AI service: {exc.reason}"
            self._note_failure(message)
            return {"ok": False, "message": None, "error": message}
        except (TimeoutError, json.JSONDecodeError, OSError) as exc:
            message = f"The AI request did not complete: {exc}"
            self._note_failure(message)
            return {"ok": False, "message": None, "error": message}

        try:
            message = raw["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            error = "The AI service returned an unexpected response."
            self._note_failure(error)
            return {"ok": False, "message": None, "error": error}

        with self._lock:
            self.last_ok = time.time()
            self.last_error = None
            self._fail_until = 0.0

        return {"ok": True, "message": message, "error": None}

    # ------------------------------------------------------------------ #
    # convenience
    # ------------------------------------------------------------------ #
    def verify(self) -> dict:
        """Lightweight health check - does NOT affect main LLM state."""
        if not self.configured:
            return {"ok": False, "error": "no API key configured"}
        # Direct HTTP call without touching shared state
        import urllib.error
        import urllib.request
        payload = {"model": self.model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5, "temperature": 0}
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {config.LLM_API_KEY}", "User-Agent": "JARVIS-Desktop/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                json.loads(resp.read().decode("utf-8"))
            return {"ok": True, "error": None}
        except urllib.error.HTTPError as exc:
            return {"ok": False, "error": f"HTTP {exc.code}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


_LLM: LLM | None = None


def get_llm() -> LLM:
    global _LLM
    if _LLM is None:
        _LLM = LLM()
    return _LLM
