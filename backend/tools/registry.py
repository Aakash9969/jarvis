"""
Tool registry.

This is the single source of truth for what the agent may do.  Each tool
declares a JSON-schema for its arguments, a risk level and a human summary
used in confirmation prompts.  Both the online LLM (function calling) and the
offline brain produce calls in exactly this shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from . import apps, files, system, web
from .safety import SafetyError

RiskFn = Callable[[dict], str]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable[..., dict]
    risk: str | RiskFn = "safe"
    summary: Callable[[dict], str] | None = None
    category: str = "general"

    def risk_for(self, args: dict) -> str:
        if callable(self.risk):
            try:
                return self.risk(args)
            except Exception:  # noqa: BLE001
                return "confirm"
        return self.risk

    def summarise(self, args: dict) -> str:
        if self.summary:
            try:
                return self.summary(args)
            except Exception:  # noqa: BLE001
                pass
        return f"Run {self.name}"


def _risk_write_file(args: dict) -> str:
    """Overwriting an existing file needs a confirmation; creating one does not."""
    from . import safety

    try:
        target = safety.resolve_path(args.get("path", ""), for_write=True)
        return "confirm" if target.exists() else "safe"
    except SafetyError:
        return "confirm"


def _summary_delete(args: dict) -> str:
    return f'Delete "{args.get("path", "?")}" permanently'


def _summary_move(args: dict) -> str:
    return f'Move "{args.get("source", "?")}" to "{args.get("destination", "?")}"'


def _summary_power(args: dict) -> str:
    action = str(args.get("action", "")).lower()
    pretty = {
        "shutdown": "Shut down the computer",
        "restart": "Restart the computer",
        "sleep": "Put the computer to sleep",
        "lock": "Lock the computer",
        "cancel": "Cancel the pending shutdown/restart",
    }.get(action, f"Run power action: {action}")
    return pretty


def _summary_empty_bin(args: dict) -> str:  # noqa: ARG001
    return "Permanently empty the Recycle Bin"


TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    TOOLS[tool.name] = tool


# --------------------------------------------------------------------------- #
# Applications & shell
# --------------------------------------------------------------------------- #
register(Tool(
    name="open_application",
    description="Launch a desktop application installed on Windows, such as Chrome, "
                "Edge, VS Code, Notepad, File Explorer, Calculator, Terminal or Spotify.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Application name, e.g. 'chrome' or 'vs code'."},
        },
        "required": ["name"],
    },
    func=apps.open_application,
    risk="safe",
    summary=lambda a: f'Open the application "{a.get("name", "?")}"',
    category="desktop",
))

register(Tool(
    name="open_folder",
    description="Open a folder in Windows File Explorer.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Folder path, e.g. '~/Documents' or 'Projects'."},
        },
        "required": ["path"],
    },
    func=apps.open_folder,
    risk="safe",
    summary=lambda a: f'Open the folder "{a.get("path", "?")}"',
    category="desktop",
))

register(Tool(
    name="open_file",
    description="Open an existing file with its default Windows application.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Path to the file to open."}},
        "required": ["path"],
    },
    func=apps.open_file,
    risk="safe",
    summary=lambda a: f'Open the file "{a.get("path", "?")}"',
    category="desktop",
))

register(Tool(
    name="reveal_in_explorer",
    description="Show a file or folder in File Explorer with the item selected.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    func=files.reveal_in_explorer,
    risk="safe",
    category="desktop",
))

# --------------------------------------------------------------------------- #
# Web
# --------------------------------------------------------------------------- #
register(Tool(
    name="open_url",
    description="Open any http(s) web address in the default browser.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Full URL or domain, e.g. 'github.com'."}},
        "required": ["url"],
    },
    func=web.open_url,
    risk="safe",
    summary=lambda a: f'Open {a.get("url", "?")} in the browser',
    category="web",
))

register(Tool(
    name="open_site",
    description="Open a well-known website by name: youtube, google, gmail, github, "
                "wikipedia, maps, netflix, spotify, reddit, linkedin and more.",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Site name, e.g. 'youtube'."}},
        "required": ["name"],
    },
    func=web.open_site,
    risk="safe",
    summary=lambda a: f'Open {a.get("name", "?")} in the browser',
    category="web",
))

register(Tool(
    name="search_web",
    description="Search the web in the browser. Use engine='youtube' to search YouTube.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to search for."},
            "engine": {
                "type": "string",
                "description": "google, bing, duckduckgo, youtube, github, stackoverflow, wikipedia or amazon.",
            },
        },
        "required": ["query"],
    },
    func=web.search_web,
    risk="safe",
    summary=lambda a: f'Search {a.get("engine", "google")} for "{a.get("query", "?")}"',
    category="web",
))

register(Tool(
    name="download_file",
    description="Download a file from a URL to the workspace/Downloads folder.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to download from."},
            "filename": {"type": "string", "description": "Optional filename to save as."},
        },
        "required": ["url"],
    },
    func=web.download_file,
    risk="safe",
    summary=lambda a: f'Download file from {a.get("url", "?")}',
    category="web",
))

# --------------------------------------------------------------------------- #
# Files & folders
# --------------------------------------------------------------------------- #
register(Tool(
    name="create_folder",
    description="Create a new folder. Relative paths are created inside the JARVIS workspace on the Desktop.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Folder name or path, e.g. 'Projects'."}},
        "required": ["path"],
    },
    func=files.create_folder,
    risk="safe",
    summary=lambda a: f'Create the folder "{a.get("path", "?")}"',
    category="files",
))

register(Tool(
    name="create_file",
    description="Create a new text-based file (e.g. .txt, .md, .py, .json, .csv) with optional content.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File name, e.g. 'meeting_notes.txt' or 'test.py'."},
            "content": {"type": "string", "description": "Optional file content."},
        },
        "required": ["path"],
    },
    func=files.create_file,
    risk="safe",
    summary=lambda a: f'Create the file "{a.get("path", "?")}"',
    category="files",
))

register(Tool(
    name="write_file",
    description="Write or replace the content of a file. Creates the file if it does not exist.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Target file, e.g. 'studyplan.txt'."},
            "content": {"type": "string", "description": "Full text to write."},
        },
        "required": ["path", "content"],
    },
    func=files.write_file,
    risk=_risk_write_file,
    summary=lambda a: f'Write content into "{a.get("path", "?")}"',
    category="files",
))

register(Tool(
    name="append_file",
    description="Add text to the end of an existing file, or create it if missing.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
    func=files.append_file,
    risk="safe",
    summary=lambda a: f'Add text to "{a.get("path", "?")}"',
    category="files",
))

register(Tool(
    name="read_file",
    description="Read a text file and show its content.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    func=files.read_file,
    risk="safe",
    summary=lambda a: f'Read "{a.get("path", "?")}"',
    category="files",
))

register(Tool(
    name="list_files",
    description="List the files and folders inside a folder.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Folder to list. Defaults to the JARVIS workspace."}},
    },
    func=files.list_files,
    risk="safe",
    summary=lambda a: f'List the contents of "{a.get("path", ".")}"',
    category="files",
))

register(Tool(
    name="move_path",
    description="Move or rename a file or folder.",
    parameters={
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "destination": {"type": "string"},
        },
        "required": ["source", "destination"],
    },
    func=files.move_path,
    risk="confirm",
    summary=_summary_move,
    category="files",
))

register(Tool(
    name="delete_path",
    description="Permanently delete a file or a folder and its contents.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    func=files.delete_path,
    risk="confirm",
    summary=_summary_delete,
    category="files",
))

register(Tool(
    name="path_info",
    description="Show details (size, type, modified time) about a file or folder.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    func=files.path_info,
    risk="safe",
    category="files",
))

# --------------------------------------------------------------------------- #
# System
# --------------------------------------------------------------------------- #
register(Tool(
    name="system_info",
    description="Report CPU, RAM, disk space, battery and OS information.",
    parameters={"type": "object", "properties": {}},
    func=system.system_info,
    risk="safe",
    summary=lambda a: "Read system status",
    category="system",
))

register(Tool(
    name="get_time",
    description="Get the current date and time.",
    parameters={"type": "object", "properties": {}},
    func=system.get_time,
    risk="safe",
    summary=lambda a: "Check the time",
    category="system",
))

register(Tool(
    name="disk_usage",
    description="Check free disk space.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Optional drive or folder, e.g. 'C:\\\\'."}},
    },
    func=system.disk_usage,
    risk="safe",
    category="system",
))

register(Tool(
    name="run_command",
    description="Run a read-only Windows diagnostic command (ipconfig, systeminfo, tasklist, "
                "ping, whoami, where, netstat, git status and similar). Anything unsafe is refused.",
    parameters={
        "type": "object",
        "properties": {"command": {"type": "string", "description": "The full command line, e.g. 'ipconfig /all'."}},
        "required": ["command"],
    },
    func=system.run_command,
    risk="safe",
    summary=lambda a: f'Run the diagnostic command "{a.get("command", "?")}"',
    category="system",
))

register(Tool(
    name="list_safe_commands",
    description="List the diagnostic commands JARVIS is allowed to run.",
    parameters={"type": "object", "properties": {}},
    func=system.list_safe_commands,
    risk="safe",
    category="system",
))

register(Tool(
    name="show_desktop",
    description="Minimise all windows and show the desktop.",
    parameters={"type": "object", "properties": {}},
    func=system.show_desktop,
    risk="safe",
    category="system",
))

register(Tool(
    name="open_task_manager",
    description="Open Windows Task Manager.",
    parameters={"type": "object", "properties": {}},
    func=system.open_task_manager,
    risk="safe",
    category="system",
))

register(Tool(
    name="system_power",
    description="Lock, sleep, shut down or restart the computer. Requires user confirmation.",
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "One of: lock, sleep, shutdown, restart, cancel."},
        },
        "required": ["action"],
    },
    func=system.system_power,
    risk="confirm",
    summary=_summary_power,
    category="system",
))

register(Tool(
    name="empty_recycle_bin",
    description="Permanently delete everything in the Recycle Bin. Requires confirmation.",
    parameters={"type": "object", "properties": {}},
    func=system.empty_recycle_bin,
    risk="confirm",
    summary=_summary_empty_bin,
    category="system",
))


# --------------------------------------------------------------------------- #
# Public helpers
# --------------------------------------------------------------------------- #
def get(name: str) -> Tool | None:
    return TOOLS.get(name)


def schemas() -> list[dict]:
    """OpenAI-style function/tool schemas for every registered tool."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in TOOLS.values()
    ]


def execute(name: str, args: dict[str, Any]) -> dict:
    """Run a tool safely. Never raises - always returns a result envelope."""
    tool = TOOLS.get(name)
    if tool is None:
        return {"ok": False, "message": f'I do not have a tool called "{name}".', "data": {}}

    args = args or {}
    # Drop unknown keys so a sloppy LLM call cannot inject surprises.
    allowed = set(tool.parameters.get("properties", {}))
    clean = {k: v for k, v in args.items() if k in allowed}

    missing = [p for p in tool.parameters.get("required", []) if not str(clean.get(p, "")).strip()]
    if missing:
        return {
            "ok": False,
            "message": f'I need more information to do that: missing {", ".join(missing)}.',
            "data": {},
        }

    try:
        result = tool.func(**clean)
    except SafetyError as exc:
        return {"ok": False, "message": str(exc), "data": {}}
    except TypeError as exc:
        return {"ok": False, "message": f"I called that tool with the wrong arguments ({exc}).", "data": {}}
    except Exception as exc:  # noqa: BLE001 - never let a tool crash the agent
        return {"ok": False, "message": f'That did not work: {exc}', "data": {}}

    if not isinstance(result, dict) or "ok" not in result:
        return {"ok": True, "message": str(result), "data": {}}
    result.setdefault("data", {})
    return result


def risk_of(name: str, args: dict) -> str:
    tool = TOOLS.get(name)
    return tool.risk_for(args) if tool else "blocked"


def summarise(name: str, args: dict) -> str:
    tool = TOOLS.get(name)
    return tool.summarise(args) if tool else f"Run {name}"


def is_known(name: str) -> bool:
    return name in TOOLS
