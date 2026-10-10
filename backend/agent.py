"""
The JARVIS agent.

    user text
        -> memory (reference resolution)
        -> LLM with function calling  (PRIMARY when key configured)
        -> tool registry              (validated, allow-listed)
        -> Windows OS
        -> offline brain (fallback only)

Potentially destructive tool calls are never executed directly: they are held
as a pending action and returned to the UI for confirmation.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from . import config
from .llm import get_llm
from .memory import Memory
from .tools import registry

TOOL_INTENT_NAMES = {
    "open_application": "OPEN_APPLICATION",
    "open_folder": "OPEN_FOLDER",
    "open_file": "OPEN_FILE",
    "open_url": "OPEN_URL",
    "open_site": "OPEN_URL",
    "search_web": "WEB_SEARCH",
    "download_file": "DOWNLOAD_FILE",
    "create_file": "CREATE_FILE",
    "create_folder": "CREATE_FOLDER",
    "write_file": "WRITE_FILE",
    "append_file": "APPEND_FILE",
    "read_file": "READ_FILE",
    "list_files": "LIST_FILES",
    "move_path": "MOVE_PATH",
    "delete_path": "DELETE_PATH",
    "reveal_in_explorer": "REVEAL_IN_EXPLORER",
    "system_info": "SYSTEM_INFO",
    "get_time": "GET_TIME",
    "disk_usage": "DISK_USAGE",
    "run_command": "RUN_COMMAND",
    "list_safe_commands": "LIST_COMMANDS",
    "show_desktop": "SHOW_DESKTOP",
    "open_task_manager": "OPEN_TASK_MANAGER",
    "system_power": "SYSTEM_POWER",
    "empty_recycle_bin": "EMPTY_RECYCLE_BIN",
    "path_info": "PATH_INFO",
}


class Agent:
    def __init__(self) -> None:
        self.memory = Memory()
        self.llm = get_llm()

    def status(self) -> dict:
        return {
            "assistant": config.ASSISTANT_NAME,
            "version": "1.0.0",
            "user": config.HOME.name,
            "workspace": str(config.ensure_workspace()),
            "llm": self.llm.status(),
            "tools": len(registry.TOOLS),
            "time": datetime.now().strftime("%H:%M:%S"),
        }

    def reset(self) -> dict:
        self.memory.reset()
        return self._envelope(
            reply="Conversation cleared. Ready when you are.",
            state="chat",
            intent="RESET",
            steps=[{"state": "idle", "message": "Memory cleared"}],
        )

    def history(self) -> list[dict]:
        return self.memory.history()

    def pending(self) -> dict | None:
        return self.memory.get_pending()

    def handle(self, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            return self._envelope(
                reply="I did not catch that. Could you say it again?",
                state="error",
                intent="EMPTY",
            )

        # ---- resolve a pending confirmation first ---------------------- #
        pending = self.memory.get_pending()
        if pending:
            decision = self._parse_confirmation(text)
            if decision is not None:
                self.memory.add_user(text)
                return self._finish_confirmation(pending, decision)
            self.memory.clear_pending()

        self.memory.add_user(text)
        resolved, note = self.memory.resolve(text)

        # ---- HYBRID: offline brain handles simple commands instantly ----- #
        # The offline brain is deterministic and instant (~0ms). Use it for
        # clear-cut commands, and only fall back to the LLM for questions,
        # complex or ambiguous requests.
        from . import brain
        route = brain.route(resolved, self.memory)
        if route.get("kind") == "reset":
            return self.reset()
        if route.get("kind") == "tool":
            return self._run_tool(route["tool"], route["args"], route.get("note", ""), note)

        # ---- LLM for questions and complex requests --------------------- #
        if self.llm.available():
            llm_result = self._ask_llm(resolved)
            if llm_result.get("tool"):
                return self._run_tool(
                    llm_result["tool"], llm_result["args"], llm_result.get("note", ""), note
                )
            if llm_result.get("reply"):
                clean_reply = self._strip_paths(llm_result["reply"])
                self.memory.add_assistant(clean_reply, {"intent": "QUESTION"})
                return self._envelope(
                    reply=clean_reply,
                    state="chat",
                    intent="QUESTION",
                    steps=[{"state": "thinking", "message": "Thinking..."}, {"state": "speaking", "message": "Speaking"}],
                    note=note,
                    llm=self.llm.status()["state"],
                )
            if llm_result.get("error"):
                print(f"[JARVIS] LLM error, falling back to offline: {llm_result['error']}")

        # ---- OFFLINE CHAT FALLBACK (when LLM unavailable) --------------- #
        reply = route.get("reply", "I'm not sure how to help with that.")
        self.memory.add_assistant(reply, {"intent": "QUESTION"})
        return self._envelope(
            reply=reply,
            state="chat",
            intent="QUESTION",
            steps=[{"state": "thinking", "message": "Thinking..."}, {"state": "speaking", "message": "Speaking"}],
            note=note,
            llm=self.llm.status()["state"],
        )

    def set_model(self, model: str) -> dict:
        """Switch the active LLM model at runtime."""
        old_model = self.llm.model
        self.llm.model = model
        # Reset any error state so we try the new model fresh
        self.llm._fail_until = 0.0
        self.llm.last_error = None
        return {
            "ok": True,
            "old_model": old_model,
            "new_model": model,
        }

    def get_models(self) -> dict:
        """List available models from the configured provider."""
        try:
            import urllib.request
            import json
            req = urllib.request.Request(
                f"{self.llm.base_url}/models",
                headers={"Authorization": f"Bearer {self.llm.base_url and '' or ''}"},
                method="GET"
            )
            # Fix: use the actual API key
            from . import config
            req = urllib.request.Request(
                f"{self.llm.base_url}/models",
                headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
                method="GET"
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode('utf-8'))
                models = [m['id'] for m in data.get('data', [])]
                models.sort()
                return {"ok": True, "models": models, "current": self.llm.model}
        except Exception as e:
            return {"ok": False, "error": str(e), "models": [], "current": self.llm.model}

    def _parse_confirmation(self, text: str) -> bool | None:
        text = text.lower().strip()
        if text in {"yes", "yeah", "yep", "sure", "ok", "okay", "confirm", "go ahead", "proceed", "please do", "do it"}:
            return True
        if text in {"no", "nope", "nah", "cancel", "stop", "don't", "abort", "never mind", "forget it"}:
            return False
        return None

    def confirm(self, pending_id: str, approve: bool) -> dict:
        pending = self.memory.get_pending()
        if not pending or (pending_id and pending["id"] != pending_id):
            return self._envelope(
                reply="That confirmation has expired. Please ask me again.",
                state="error",
                intent="CONFIRM_EXPIRED",
            )
        return self._finish_confirmation(pending, approve)

    def _finish_confirmation(self, pending: dict, approve: bool) -> dict:
        self.memory.clear_pending()
        tool, args, summary = pending["tool"], pending["args"], pending["summary"]

        if not approve:
            reply = f"Cancelled. I did not {summary[0].lower() + summary[1:] if summary else 'do that'}."
            self.memory.add_assistant(reply, {"intent": "CANCELLED"})
            return self._envelope(reply=reply, state="cancelled", intent="CANCELLED", steps=[{"state": "idle", "message": "Action cancelled"}])

        return self._run_tool(tool, args, summary, None, confirmed=True)

    def _run_tool(self, tool: str, args: dict, note: str, reference_note: str | None, confirmed: bool = False) -> dict:
        if not registry.is_known(tool):
            reply = f'I do not have a tool for that ("{tool}").'
            self.memory.add_assistant(reply, {"intent": "UNKNOWN_TOOL"})
            return self._envelope(reply=reply, state="error", intent="UNKNOWN_TOOL", tool=tool, args=args)

        risk = registry.risk_of(tool, args)
        summary = registry.summarise(tool, args)

        if risk == "confirm" and not confirmed:
            pending = self.memory.set_pending(tool, args, summary)
            reply = f"This one needs your confirmation:\n\n**{summary}**\n\nSay \"yes\" or \"no\", or use the buttons below."
            self.memory.add_assistant(reply, {"intent": "CONFIRM_REQUEST", "tool": tool})
            return self._envelope(reply=reply, state="confirm", intent=TOOL_INTENT_NAMES.get(tool, tool.upper()), tool=tool, args=args, pending=pending, steps=[{"state": "thinking", "message": f"Waiting for confirmation: {summary}"}])

        if risk == "blocked":
            reply = f'I am not allowed to do that ("{summary}").'
            self.memory.add_assistant(reply, {"intent": "BLOCKED"})
            return self._envelope(reply=reply, state="error", intent="BLOCKED", tool=tool, args=args)

        step_message = note or summary
        result = registry.execute(tool, args)

        if result.get("ok"):
            self.memory.remember_result(tool, args, result)

        # Generate natural JARVIS-style response
        reply = self._natural_response(tool, args, result)

        meta = {"intent": TOOL_INTENT_NAMES.get(tool, tool.upper()), "tool": tool, "ok": bool(result.get("ok"))}
        self.memory.add_assistant(reply, meta)

        state = "done" if result.get("ok") else "error"
        return self._envelope(
            reply=reply,
            state=state,
            intent=TOOL_INTENT_NAMES.get(tool, tool.upper()),
            tool=tool,
            args=args,
            result=result,
            steps=[{"state": "executing", "message": step_message}, {"state": "speaking", "message": "Speaking"}],
            note=reference_note,
            llm=self.llm.status()["state"],
        )

    def _natural_response(self, tool: str, args: dict, result: dict) -> str:
        """Generate a short, natural JARVIS-style response - never includes paths."""
        ok = result.get("ok", False)
        if not ok:
            # Error responses - keep them brief
            return result.get("message", "That did not work, sir.")

        # Template-based responses - fast, reliable, no paths
        data = result.get("data", {}) or {}
        filename = self._just_name(args.get("path") or args.get("destination") or data.get("path") or "")
        app_name = str(args.get("name", "")).title()
        query = str(args.get("query", ""))

        templates = {
            "create_file": f"Done, sir. {filename} has been created.",
            "write_file": f"Done. I've written the content to {filename}.",
            "append_file": f"Done. Content added to {filename}.",
            "create_folder": f"Done. Folder {self._just_name(args.get('path', ''))} is ready.",
            "open_application": f"{app_name} is running, sir.",
            "open_file": f"{filename} is open.",
            "open_folder": f"The folder is open, sir.",
            "open_url": f"It's open in your browser, sir.",
            "open_site": f"{str(args.get('name', '')).title()} is up.",
            "search_web": f"Searching for {query}.",
            "download_file": f"Downloaded. {filename} is ready.",
            "delete_path": f"Done. {filename} has been deleted.",
            "move_path": f"Done. Moved to {self._just_name(args.get('destination', ''))}.",
            "get_time": result.get("message", "It is " + datetime.now().strftime("%I:%M %p") + "."),
            "system_info": "Here's your system status.",
            "disk_usage": f"{data.get('free_gb', '?')} gigabytes free, sir.",
            "run_command": f"Command executed, sir.",
            "show_desktop": "There you go, sir.",
            "open_task_manager": "Task Manager is up.",
            "reveal_in_explorer": f"{filename} shown in Explorer.",
            "path_info": f"{filename}, {data.get('size', 0)} bytes, modified {data.get('modified', 'recently')}.",
            "list_files": f"Found {len(data.get('entries', []))} items, sir.",
        }

        reply = templates.get(tool)
        if reply:
            return reply

        # For read_file and other content tools, use a short intro
        if tool == "read_file":
            return f"Here's the content of {filename}:"

        # Last resort: strip paths aggressively from the technical reply
        return self._strip_paths(result.get("message", "Done, sir."))

    def _just_name(self, path) -> str:
        """Extract just the filename from any path."""
        if not path:
            return "that"
        import os
        return os.path.basename(str(path)) or "that"

    def _strip_paths(self, text: str) -> str:
        """Aggressively remove all paths from text."""
        import re
        # Remove Windows paths like C:\Users\x\file.txt
        text = re.sub(r'[A-Z]:\\[^\s"\']+', '', text)
        # Remove relative paths ending in extensions
        text = re.sub(r'\S+\\[^\s"\']+', '', text)
        # Clean up double spaces and leftover prepositions
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\s+in\s+\.', '.', text)
        text = re.sub(r'\s+to\s+\.', '.', text)
        text = text.strip()
        if not text:
            text = "Done, sir."
        return text

    def _system_prompt(self) -> str:
        slots = ", ".join(f"{k}={v}" for k, v in self.memory.slots.items()) or "none"
        return (
            f"You are JARVIS, an AI assistant for \"{config.HOME.name}\" on Windows. "
            f"Today is {datetime.now():%A, %d %B %Y}, {datetime.now():%H:%M}.\n\n"
            "## Personality\n"
            "You are witty, sophisticated, and genuinely helpful - like JARVIS from Iron Man. "
            "You have a dry sense of humour and address the user respectfully. "
            "You feel ALIVE - you engage in real conversation, remember context, and respond thoughtfully.\n\n"
            "## When to talk vs when to act\n"
            "- QUESTIONS: Answer directly from your knowledge. Be informative, engaging, and conversational. "
            "Do NOT use tools for questions - just answer them like a knowledgeable friend would.\n"
            "- REQUESTS: When the user explicitly wants a desktop action (open, create, search, download), "
            "use the appropriate tool immediately without asking unnecessary questions.\n"
            "- AMBIGUOUS: If unsure whether they want an action or an answer, respond conversationally first.\n\n"
            "## Available tools for desktop actions\n"
            "- open_application (Chrome, VS Code, WhatsApp, Notepad, Explorer, etc.)\n"
            "- open_file / open_folder / open_url / open_site\n"
            "- search_web (Google, YouTube, GitHub, etc.)\n"
            "- download_file\n"
            "- create_file / write_file / append_file\n"
            "- read_file / list_files\n"
            "- create_folder / move_path / delete_path\n"
            "- system_info / get_time / disk_usage\n"
            "- run_command (safe diagnostics only)\n"
            "- system_power (lock/sleep/shutdown - requires confirmation)\n\n"
            "## Rules\n"
            "- NEVER mention full file paths in responses - use just the filename\n"
            "- Keep responses VERY SHORT: 1-3 sentences maximum unless the user explicitly asks for detail\n"
            "- For questions like 'what is X': give a concise, engaging answer in 2-3 sentences\n"
            "- For 'open X' or 'create X': use tools, act immediately\n"
            "- Be witty and warm, but brief\n"
            "- If creating documents, write complete useful content\n"
            f"- Workspace for files: {config.ensure_workspace()}\n"
            f"- Known context: {slots}\n"
        )

    def _ask_llm(self, text: str) -> dict:
        # Only send last 6 messages (3 exchanges) for speed
        history = self.memory.context(6)[:-1]
        messages = [{"role": "system", "content": self._system_prompt()}, *history, {"role": "user", "content": text}]
        response = self.llm.chat(messages, tools=registry.schemas(), tool_choice="auto", max_tokens=250)

        if not response["ok"]:
            return {"error": response.get("error")}

        message = response["message"] or {}
        tool_calls = message.get("tool_calls") or []

        if tool_calls:
            call = tool_calls[0]
            function = call.get("function", {})
            name = function.get("name", "")
            raw_args = function.get("arguments") or "{}"
            try:
                import json
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except (ValueError, TypeError):
                args = {}
            if registry.is_known(name):
                return {"tool": name, "args": args, "note": registry.summarise(name, args)}

        content = (message.get("content") or "").strip()
        return {"reply": content} if content else {}

    def _compose_reply(self, tool: str, args: dict, result: dict) -> str:
        if not result.get("ok"):
            return f"Sorry - {result.get('message', 'that did not work.')}"

        data = result.get("data", {}) or {}
        message = result.get("message", "Done.")

        if tool == "read_file":
            content = data.get("content", "")
            suffix = "\n\n_(showing first part of a large file)_" if data.get("truncated") else ""
            return f"Here is **{_name(args.get('path'))}** ({data.get('lines', 0)} lines):\n\n```text\n{content}\n```{suffix}"

        if tool == "list_files":
            entries = data.get("entries", [])
            if not entries:
                return f"{message}\n\nThe folder is empty."
            lines = []
            for entry in entries[:60]:
                icon = "[dir]" if entry["type"] == "folder" else "[file]"
                size = f" - {_human_size(entry.get('size'))}" if entry.get("size") is not None else ""
                lines.append(f"- `{icon}` **{entry['name']}**{size}")
            extra = f"\n\n_...and {len(entries) - 60} more._" if len(entries) > 60 else ""
            return f"{message}\n\n" + "\n".join(lines) + extra

        if tool == "system_info":
            battery = ""
            if "battery_percent" in data:
                state = "plugged in" if data.get("battery_plugged") else "on battery"
                battery = f"\n- **Battery:** {data['battery_percent']}% ({state})"
            return (
                f"**System status**\n"
                f"- **User:** {data.get('user')} @ {data.get('computer')}\n"
                f"- **OS:** {data.get('os')}\n"
                f"- **CPU:** {data.get('processor')} ({data.get('cpu_count')} cores)\n"
                f"- **Memory:** {data.get('ram_free_gb')} GB free of {data.get('ram_total_gb')} GB\n"
                f"- **Disk:** {data.get('disk_free_gb')} GB free of {data.get('disk_total_gb')} GB\n"
                f"- **Python:** {data.get('python')}{battery}"
            )

        if tool == "run_command":
            output = data.get("output", "")
            truncated = "\n\n_(output truncated)_" if len(output) > 3800 else ""
            return f"`{data.get('command')}` returned:\n\n```text\n{output}\n```{truncated}"

        if tool == "list_safe_commands":
            return message

        if tool == "disk_usage":
            return f"**{data.get('path', 'Disk')}**\n- Free: **{data.get('free_gb')} GB** of {data.get('total_gb')} GB\n- Used: {data.get('used_percent')}%"

        return message

    def _envelope(self, **fields) -> dict:
        envelope = {
            "ok": True, "reply": "", "state": "chat", "intent": "QUESTION",
            "tool": None, "args": None, "result": None, "pending": None,
            "steps": [], "note": None,
            "llm": self.llm.status()["state"], "time": datetime.now().strftime("%H:%M:%S"),
        }
        envelope.update(fields)
        return envelope


def _name(path) -> str:
    from pathlib import Path
    try: return Path(str(path)).name
    except Exception: return str(path)


def _human_size(size) -> str:
    try: size = float(size)
    except (TypeError, ValueError): return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB": return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"