"""
Conversation memory.

Deliberately simple: a bounded list of turns plus a small set of "slots"
(last file, last folder, last app, ...) that let the assistant resolve
pronouns such as "it" or "that folder".
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from . import config

MAX_TURNS = 200

_FILE_PRONOUNS = re.compile(
    r"\b(it|that file|this file|the file|that document|the document|that doc|the doc|"
    r"that text file|the text file|that script|the script|the same file|that one)\b",
    re.IGNORECASE,
)
_FOLDER_PRONOUNS = re.compile(
    r"\b(that folder|this folder|the folder|that directory|the directory|that dir|the dir)\b",
    re.IGNORECASE,
)
_APP_PRONOUNS = re.compile(r"\b(it again|that app|the app)\b", re.IGNORECASE)


class Memory:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.MEMORY_FILE
        self.turns: list[dict] = []
        self.slots: dict[str, Any] = {}
        self.pending: dict | None = None
        self._lock = threading.RLock()
        self.load()

    # ------------------------------------------------------------------ #
    # persistence
    # ------------------------------------------------------------------ #
    def load(self) -> None:
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self.turns = raw.get("turns", [])[-MAX_TURNS:]
                self.slots = raw.get("slots", {})
        except (OSError, json.JSONDecodeError):
            self.turns, self.slots = [], {}

    def save(self) -> None:
        try:
            self.path.write_text(
                json.dumps({"turns": self.turns[-MAX_TURNS:], "slots": self.slots}, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    # turns
    # ------------------------------------------------------------------ #
    def add_user(self, text: str) -> None:
        with self._lock:
            self.turns.append({"role": "user", "text": text, "ts": time.time()})
            self.turns = self.turns[-MAX_TURNS:]
            self.save()

    def add_assistant(self, text: str, meta: dict | None = None) -> None:
        with self._lock:
            self.turns.append({"role": "assistant", "text": text, "ts": time.time(), "meta": meta or {}})
            self.turns = self.turns[-MAX_TURNS:]
            self.save()

    def context(self, limit: int | None = None) -> list[dict]:
        limit = limit or config.LLM_MAX_HISTORY
        recent = self.turns[-limit:]
        return [{"role": t["role"], "content": t["text"]} for t in recent]

    def history(self) -> list[dict]:
        return list(self.turns)

    def reset(self) -> None:
        with self._lock:
            self.turns, self.slots, self.pending = [], {}, None
            self.save()

    # ------------------------------------------------------------------ #
    # slots / references
    # ------------------------------------------------------------------ #
    def set_slot(self, key: str, value: Any) -> None:
        with self._lock:
            if value not in (None, ""):
                self.slots[key] = value
                self.save()

    def get_slot(self, key: str) -> Any:
        return self.slots.get(key)

    def remember_result(self, tool: str, args: dict, result: dict) -> None:
        """Update slots based on what a tool just did."""
        data = result.get("data", {}) or {}
        path = data.get("path") or args.get("path") or args.get("destination")

        if tool in {"create_file", "write_file", "append_file", "read_file", "open_file", "path_info"}:
            if path:
                self.set_slot("last_file", str(path))
                self.set_slot("last_folder", str(Path(path).parent))
        elif tool in {"create_folder", "open_folder", "list_files"}:
            if path:
                self.set_slot("last_folder", str(path))
        elif tool == "move_path":
            if path:
                self.set_slot("last_file", str(path))
                self.set_slot("last_folder", str(Path(path).parent))
        elif tool == "open_application":
            self.set_slot("last_app", data.get("app") or args.get("name"))
        elif tool in {"open_url", "open_site"}:
            self.set_slot("last_url", data.get("url") or args.get("url") or args.get("name"))
        elif tool == "search_web":
            self.set_slot("last_query", args.get("query"))
            self.set_slot("last_url", data.get("url"))

    def resolve(self, text: str) -> tuple[str, str | None]:
        """
        Replace pronouns with remembered entities.

        Returns ``(new_text, note)`` where *note* describes the substitution.
        """
        if not text:
            return text, None

        lowered = text.lower()

        # Skip resolution for time/date/weather questions where "it" is
        # a dummy pronoun, not a reference to a file.
        dummy_patterns = [
            "what time is", "what's the time", "whats the time",
            "what is the time", "what day is", "what's the date",
            "what is the date", "how is the weather", "what's the weather",
            "how's it going", "hows it going", "how are you",
        ]
        for pattern in dummy_patterns:
            if pattern in lowered:
                return text, None

        note = None

        last_file = self.slots.get("last_file")
        last_folder = self.slots.get("last_folder")

        # Only resolve a file pronoun when the sentence is not obviously about
        # the last folder, and vice versa.
        folder_hit = _FOLDER_PRONOUNS.search(text)
        file_hit = _FILE_PRONOUNS.search(text)

        if folder_hit and last_folder and (not file_hit or lowered.index(folder_hit.group(1).lower()) <= lowered.index(file_hit.group(1).lower())):
            text = _FOLDER_PRONOUNS.sub(lambda _m: str(last_folder), text, count=1)
            note = f'folder "{Path(last_folder).name}"'
            return text, note

        if file_hit and last_file:
            text = _FILE_PRONOUNS.sub(lambda _m: str(last_file), text, count=1)
            note = f'file "{Path(last_file).name}"'
            return text, note

        if folder_hit and last_folder:
            text = _FOLDER_PRONOUNS.sub(lambda _m: str(last_folder), text, count=1)
            note = f'folder "{Path(last_folder).name}"'

        return text, note

    # ------------------------------------------------------------------ #
    # pending confirmation
    # ------------------------------------------------------------------ #
    def set_pending(self, tool: str, args: dict, summary: str, ttl: float = 180.0) -> dict:
        with self._lock:
            self.pending = {
                "id": uuid.uuid4().hex[:10],
                "tool": tool,
                "args": args,
                "summary": summary,
                "created": time.time(),
                "expires": time.time() + ttl,
            }
            return self.pending

    def get_pending(self) -> dict | None:
        pending = self.pending
        if pending and time.time() > pending.get("expires", 0):
            self.pending = None
            return None
        return pending

    def clear_pending(self) -> None:
        with self._lock:
            self.pending = None
