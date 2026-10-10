"""
Path and command safety validation.

Every desktop tool funnels through this module so that the assistant can never
silently touch system locations or run arbitrary shell strings.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .. import config


class SafetyError(Exception):
    """Raised when a requested path/command violates the safety policy."""


# --------------------------------------------------------------------------- #
# Blocked locations (never written to, never deleted from)
# --------------------------------------------------------------------------- #
def _safe_resolve(raw: str) -> Path:
    try:
        return Path(raw).resolve()
    except (OSError, ValueError):
        return Path(raw)


SYSTEM_ROOT = Path(os.environ.get("SystemRoot", r"C:\Windows"))
PROGRAM_FILES = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
PROGRAM_FILES_X86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
PROGRAM_DATA = Path(os.environ.get("ProgramData", r"C:\ProgramData"))

BLOCKED_ROOTS: list[Path] = [
    _safe_resolve(str(SYSTEM_ROOT)),
    _safe_resolve(str(PROGRAM_FILES)),
    _safe_resolve(str(PROGRAM_FILES_X86)),
    _safe_resolve(str(PROGRAM_DATA)),
    _safe_resolve(r"C:\$Recycle.Bin"),
    _safe_resolve(r"C:\Recovery"),
    _safe_resolve(r"C:\PerfLogs"),
    _safe_resolve(str(config.ROOT)),
]

# Folders a user may freely create/read/delete inside.
ALLOWED_ROOTS: list[Path] = [config.HOME, config.TEMP]

# Characters that make a filename dangerous on Windows.
_ILLEGAL_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def clean_name(name: str) -> str:
    """Validate a bare file/folder name (no directory separators)."""
    name = (name or "").strip().strip('"').strip("'").strip()
    name = name.rstrip(".")
    if not name:
        raise SafetyError("The name was empty.")
    if len(name) > 180:
        raise SafetyError("That name is too long.")
    if _ILLEGAL_NAME.search(name):
        raise SafetyError(f'"{name}" contains characters that are not allowed in a name.')
    if name.split(".")[0].upper() in _RESERVED_NAMES:
        raise SafetyError(f'"{name}" is a reserved Windows name.')
    if name in (".", ".."):
        raise SafetyError("That name is not allowed.")
    return name


def _expand(raw: str) -> str:
    raw = (raw or "").strip().strip('"').strip("'")
    raw = raw.replace("/", os.sep)
    raw = os.path.expandvars(raw)
    return raw


def resolve_path(
    raw: str,
    *,
    for_write: bool = False,
    must_exist: bool = False,
    allow_outside_home: bool = False,
) -> Path:
    """
    Turn user supplied text into a concrete, validated Path.

    ``allow_outside_home`` is used by read-only "open/read" operations so the
    user can still open a file in e.g. D:\\projects, while every *write* stays
    inside the user profile or temp directory.
    """
    text = _expand(raw)
    if not text:
        raise SafetyError("No path was given.")

    path = Path(text).expanduser()
    if not path.is_absolute():
        base = config.ensure_workspace()
        path = base / path

    try:
        path = path.resolve()
    except OSError:
        path = Path(os.path.abspath(str(path)))

    for blocked in BLOCKED_ROOTS:
        if path == blocked or _is_inside(path, blocked):
            raise SafetyError(
                f'"{path}" is inside a protected system location, so I will not touch it.'
            )

    inside_allowed = any(_is_inside(path, root) or path == root for root in ALLOWED_ROOTS)
    if not inside_allowed and not allow_outside_home:
        raise SafetyError(
            f'"{path}" is outside your user folder. I only create or change files '
            f"inside {config.HOME}."
        )

    if must_exist and not path.exists():
        raise SafetyError(f'I could not find "{path}".')

    return path


def require_existing_file(raw: str) -> Path:
    path = resolve_path(raw, must_exist=True, allow_outside_home=True)
    if not path.is_file():
        raise SafetyError(f'"{path}" is not a file.')
    return path


def require_existing_dir(raw: str) -> Path:
    path = resolve_path(raw, must_exist=True, allow_outside_home=True)
    if not path.is_dir():
        raise SafetyError(f'"{path}" is not a folder.')
    return path


# --------------------------------------------------------------------------- #
# Shell command policy
# --------------------------------------------------------------------------- #
# Read-only, harmless diagnostics that may run without confirmation.
SAFE_COMMANDS: dict[str, dict] = {
    "ipconfig": {"args": ["/all", "/flushdns", "/displaydns", "/release", "/renew", ""], "note": "network configuration"},
    "systeminfo": {"args": [""], "note": "system summary"},
    "tasklist": {"args": ["", "/v"], "note": "running processes"},
    "whoami": {"args": [""], "note": "current user"},
    "hostname": {"args": [""], "note": "computer name"},
    "ver": {"args": [""], "note": "windows version"},
    "where": {"args": None, "note": "locate an executable"},
    "ping": {"args": None, "note": "network reachability"},
    "getmac": {"args": ["", "/v"], "note": "mac addresses"},
    "date": {"args": [""], "note": "current date"},
    "time": {"args": [""], "note": "current time"},
    "tree": {"args": None, "note": "folder tree"},
    "dir": {"args": None, "note": "folder listing"},
    "echo": {"args": None, "note": "print text"},
    "python": {"args": ["--version"], "note": "python version"},
    "node": {"args": ["--version"], "note": "node version"},
    "pip": {"args": ["--version"], "note": "pip version"},
    "git": {"args": ["--version", "status", "log", "branch", "-C"], "note": "git info"},
    "nslookup": {"args": None, "note": "dns lookup"},
    "netstat": {"args": ["", "-an", "-rn"], "note": "network sockets"},
    "driverquery": {"args": [""], "note": "installed drivers"},
}

# Patterns that are never executed, even after an explicit confirmation.
DANGEROUS_PATTERNS = [
    r"\bformat\b", r"\bdiskpart\b", r"\bmkfs\b", r"\bdel\s+/[fsq]", r"\brm\s+-rf\b",
    r"\brd\s+/s\b", r"\brmdir\s+/s\b", r"\breg\s+delete\b", r"\breg\s+add\b",
    r"\bbcdedit\b", r"\bshutdown\b", r"\btaskkill\b", r"\bnet\s+user\b",
    r"\bvssadmin\b", r"\bcipher\s+/w\b", r"\btakeown\b", r"\bicacls\b",
    r"\bsc\s+delete\b", r"\battrib\s+-", r"\bpowershell\b", r"\bcmd\s+/c\b",
    r"\bwmic\b", r"\bmsconfig\b", r"\bregedit\b", r"\bcontrol\b",
    r"\brm\b", r"\bdel\b", r"\bmove\b", r"\bcopy\b",
]

# Shell metacharacters - never allowed in a command we execute.
_SHELL_META = re.compile(r"[&|;<>`$\n\r%\^]")


def vet_command(command: str) -> dict:
    """
    Inspect a shell command string.

    Returns ``{"ok": bool, "auto": bool, "reason": str, "argv": [str, ...]}``.
    ``auto`` means it is on the read-only allow-list and may run immediately.
    """
    command = (command or "").strip()
    if not command:
        return {"ok": False, "auto": False, "reason": "No command was given.", "argv": []}

    if len(command) > 300:
        return {"ok": False, "auto": False, "reason": "That command is too long.", "argv": []}

    if _SHELL_META.search(command):
        return {
            "ok": False,
            "auto": False,
            "reason": "That command contains shell operators, which I never run.",
            "argv": [],
        }

    lowered = command.lower()
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, lowered):
            return {
                "ok": False,
                "auto": False,
                "reason": "That command is on my permanent block list for safety.",
                "argv": [],
            }

    parts = command.split()
    program = parts[0].lower()
    if program.endswith(".exe"):
        program = program[:-4]
    if program not in SAFE_COMMANDS:
        return {
            "ok": False,
            "auto": False,
            "reason": f'"{parts[0]}" is not on my list of safe commands.',
            "argv": [],
        }

    spec = SAFE_COMMANDS[program]
    args = parts[1:]
    allowed_args = spec.get("args")
    if allowed_args is not None and args:
        joined = " ".join(args)
        if not any(joined == a or joined.startswith(a + " ") for a in allowed_args if a):
            # e.g. "pip install X" is not a read-only pip call
            return {
                "ok": False,
                "auto": False,
                "reason": f'Those arguments for "{program}" are not on my safe list.',
                "argv": [],
            }
    elif allowed_args is not None and not args and "" not in allowed_args:
        return {
            "ok": False,
            "auto": False,
            "reason": f'"{program}" needs arguments I do not allow.',
            "argv": [],
        }

    return {"ok": True, "auto": True, "reason": "Read-only diagnostic command.", "argv": parts}
