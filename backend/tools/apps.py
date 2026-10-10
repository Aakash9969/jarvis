"""Launching applications and opening folders/files on Windows."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .. import config
from . import safety

try:  # winreg only exists on Windows
    import winreg  # type: ignore
except ImportError:  # pragma: no cover
    winreg = None  # type: ignore


def _ok(message: str, **data) -> dict:
    return {"ok": True, "message": message, "data": data}


def _err(message: str, **data) -> dict:
    return {"ok": False, "message": message, "data": data}


# --------------------------------------------------------------------------- #
# Known application catalogue (aliases -> candidate executables)
# --------------------------------------------------------------------------- #
KNOWN_APPS: dict[str, dict] = {
    "chrome": {
        "label": "Google Chrome",
        "aliases": ["chrome", "google chrome", "google", "browser"],
        "paths": [
            r"{PROGRAMFILES}\Google\Chrome\Application\chrome.exe",
            r"{PROGRAMFILES(X86)}\Google\Chrome\Application\chrome.exe",
            r"{LOCALAPPDATA}\Google\Chrome\Application\chrome.exe",
        ],
        "app_paths": ["chrome.exe"],
        "which": ["chrome", "chrome.exe"],
    },
    "edge": {
        "label": "Microsoft Edge",
        "aliases": ["edge", "microsoft edge", "msedge"],
        "paths": [
            r"{PROGRAMFILES(X86)}\Microsoft\Edge\Application\msedge.exe",
            r"{PROGRAMFILES}\Microsoft\Edge\Application\msedge.exe",
        ],
        "app_paths": ["msedge.exe"],
        "which": ["msedge", "msedge.exe"],
    },
    "firefox": {
        "label": "Mozilla Firefox",
        "aliases": ["firefox", "mozilla firefox", "mozilla"],
        "paths": [
            r"{PROGRAMFILES}\Mozilla Firefox\firefox.exe",
            r"{PROGRAMFILES(X86)}\Mozilla Firefox\firefox.exe",
        ],
        "app_paths": ["firefox.exe"],
        "which": ["firefox", "firefox.exe"],
    },
    "vscode": {
        "label": "Visual Studio Code",
        "aliases": ["vs code", "vscode", "code", "visual studio code"],
        "paths": [
            r"{LOCALAPPDATA}\Programs\Microsoft VS Code\Code.exe",
            r"{PROGRAMFILES}\Microsoft VS Code\Code.exe",
        ],
        "app_paths": ["Code.exe"],
        "which": ["code", "code.cmd"],
    },
    "explorer": {
        "label": "File Explorer",
        "aliases": ["file explorer", "explorer", "files", "my computer", "this pc"],
        "paths": [r"{WINDIR}\explorer.exe"],
        "app_paths": ["explorer.exe"],
        "which": ["explorer", "explorer.exe"],
        "special": "explorer",
    },
    "notepad": {
        "label": "Notepad",
        "aliases": ["notepad", "text editor"],
        "paths": [r"{WINDIR}\notepad.exe"],
        "app_paths": ["notepad.exe"],
        "which": ["notepad", "notepad.exe"],
    },
    "calculator": {
        "label": "Calculator",
        "aliases": ["calculator", "calc"],
        "paths": [r"{WINDIR}\System32\calc.exe"],
        "app_paths": ["calc.exe"],
        "which": ["calc", "calc.exe"],
    },
    "paint": {
        "label": "Paint",
        "aliases": ["paint", "ms paint"],
        "paths": [r"{WINDIR}\System32\mspaint.exe"],
        "app_paths": ["mspaint.exe"],
        "which": ["mspaint", "mspaint.exe"],
    },
    "cmd": {
        "label": "Command Prompt",
        "aliases": ["command prompt", "cmd", "terminal", "console"],
        "paths": [r"{WINDIR}\System32\cmd.exe"],
        "app_paths": ["cmd.exe"],
        "which": ["cmd", "cmd.exe"],
        "special": "new_terminal",
    },
    "powershell": {
        "label": "PowerShell",
        "aliases": ["powershell", "power shell"],
        "paths": [r"{WINDIR}\System32\WindowsPowerShell\v1.0\powershell.exe"],
        "app_paths": ["powershell.exe"],
        "which": ["powershell", "powershell.exe"],
        "special": "new_terminal",
    },
    "terminal": {
        "label": "Windows Terminal",
        "aliases": ["windows terminal", "wt"],
        "paths": [r"{LOCALAPPDATA}\Microsoft\WindowsApps\wt.exe"],
        "app_paths": ["wt.exe"],
        "which": ["wt", "wt.exe"],
        "special": "new_terminal",
    },
    "task manager": {
        "label": "Task Manager",
        "aliases": ["task manager", "taskmgr"],
        "paths": [r"{WINDIR}\System32\Taskmgr.exe"],
        "app_paths": ["taskmgr.exe"],
        "which": ["taskmgr", "taskmgr.exe"],
    },
    "settings": {
        "label": "Windows Settings",
        "aliases": ["settings", "windows settings"],
        "paths": [],
        "app_paths": [],
        "which": [],
        "special": "ms-settings:",
    },
    "control panel": {
        "label": "Control Panel",
        "aliases": ["control panel"],
        "paths": [],
        "app_paths": [],
        "which": [],
        "special": "control",
    },
    "spotify": {
        "label": "Spotify",
        "aliases": ["spotify"],
        "paths": [
            r"{APPDATA}\Spotify\Spotify.exe",
            r"{LOCALAPPDATA}\Microsoft\WindowsApps\Spotify.exe",
        ],
        "app_paths": ["Spotify.exe"],
        "which": ["spotify", "spotify.exe"],
    },
    "discord": {
        "label": "Discord",
        "aliases": ["discord"],
        "paths": [r"{LOCALAPPDATA}\Discord\Update.exe"],
        "app_paths": [],
        "which": ["discord", "discord.exe"],
    },
    "steam": {
        "label": "Steam",
        "aliases": ["steam"],
        "paths": [
            r"{PROGRAMFILES(X86)}\Steam\steam.exe",
            r"{PROGRAMFILES}\Steam\steam.exe",
        ],
        "app_paths": ["steam.exe"],
        "which": [],
    },
    "word": {
        "label": "Microsoft Word",
        "aliases": ["word", "microsoft word", "ms word"],
        "paths": [r"{PROGRAMFILES}\Microsoft Office\root\Office16\WINWORD.EXE"],
        "app_paths": ["WINWORD.EXE"],
        "which": [],
    },
    "excel": {
        "label": "Microsoft Excel",
        "aliases": ["excel", "microsoft excel", "ms excel"],
        "paths": [r"{PROGRAMFILES}\Microsoft Office\root\Office16\EXCEL.EXE"],
        "app_paths": ["EXCEL.EXE"],
        "which": [],
    },
    "whatsapp": {
        "label": "WhatsApp",
        "aliases": ["whatsapp", "whats app", "wa"],
        "paths": [
            r"{LOCALAPPDATA}\WhatsApp\WhatsApp.exe",
            r"{PROGRAMFILES}\WhatsApp\WhatsApp.exe",
            r"{PROGRAMFILES(X86)}\WhatsApp\WhatsApp.exe",
        ],
        "app_paths": ["WhatsApp.exe"],
        "which": ["whatsapp"],
    },
    "telegram": {
        "label": "Telegram",
        "aliases": ["telegram", "tg"],
        "paths": [r"{LOCALAPPDATA}\Telegram Desktop\Telegram.exe"],
        "app_paths": ["Telegram.exe"],
        "which": ["telegram"],
    },
    "zoom": {
        "label": "Zoom",
        "aliases": ["zoom", "zoom meeting"],
        "paths": [r"{APPDATA}\Zoom\bin\Zoom.exe"],
        "app_paths": ["Zoom.exe"],
        "which": ["zoom"],
    },
    "teams": {
        "label": "Microsoft Teams",
        "aliases": ["teams", "microsoft teams", "ms teams"],
        "paths": [r"{LOCALAPPDATA}\Microsoft\Teams\Update.exe"],
        "app_paths": [],
        "which": ["teams"],
    },
    "slack": {
        "label": "Slack",
        "aliases": ["slack"],
        "paths": [r"{LOCALAPPDATA}\slack\slack.exe"],
        "app_paths": ["slack.exe"],
        "which": ["slack"],
    },
    "vlc": {
        "label": "VLC Media Player",
        "aliases": ["vlc", "vlc media player", "media player"],
        "paths": [
            r"{PROGRAMFILES}\VideoLAN\VLC\vlc.exe",
            r"{PROGRAMFILES(X86)}\VideoLAN\VLC\vlc.exe",
        ],
        "app_paths": ["vlc.exe"],
        "which": ["vlc"],
    },
    "wordpad": {
        "label": "WordPad",
        "aliases": ["wordpad"],
        "paths": [r"{PROGRAMFILES}\Windows NT\Accessories\wordpad.exe"],
        "app_paths": ["wordpad.exe"],
        "which": ["write", "wordpad"],
    },
}

_ALIAS_LOOKUP: dict[str, str] = {}
for _key, _spec in KNOWN_APPS.items():
    _ALIAS_LOOKUP[_key] = _key
    for _alias in _spec.get("aliases", []):
        _ALIAS_LOOKUP[_alias.lower()] = _key


def _expand_path(template: str) -> str:
    return os.path.expandvars(template)


def _find_in_app_paths(exe_name: str) -> str | None:
    """Look up a Windows 'App Paths' registration (works for most installers)."""
    if winreg is None:
        return None

    candidates = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
    ]
    for hive, base in candidates:
        try:
            with winreg.OpenKey(hive, f"{base}\\{exe_name}") as key:
                value, _ = winreg.QueryValueEx(key, None)
                if value and Path(value).exists():
                    return str(value)
        except OSError:
            continue
    return None


def _find_in_start_menu(term: str) -> str | None:
    """Search Start Menu shortcuts for a fuzzy match."""
    term = term.lower().replace(" ", "")
    roots = [
        Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
        Path(os.environ.get("ProgramData", "")) / r"Microsoft\Windows\Start Menu\Programs",
    ]
    best: tuple[int, str] | None = None
    for root in roots:
        if not root.exists():
            continue
        try:
            for lnk in root.rglob("*.lnk"):
                stem = lnk.stem.lower().replace(" ", "")
                if stem == term:
                    score = 0
                elif term in stem or stem in term:
                    score = 1
                else:
                    continue
                if best is None or score < best[0]:
                    best = (score, str(lnk))
        except (OSError, PermissionError):
            continue
    return best[1] if best else None


def resolve_application(name: str) -> tuple[str | None, str]:
    """Resolve a spoken app name into something launchable. Returns (target, label)."""
    raw = (name or "").strip().strip('"').strip("'")
    if not raw:
        return None, ""
    lowered = raw.lower()
    key = _ALIAS_LOOKUP.get(lowered)
    spec = KNOWN_APPS.get(key) if key else None

    if spec:
        if spec.get("special"):
            return spec["special"], spec["label"]
        for template in spec.get("paths", []):
            candidate = Path(_expand_path(template))
            if candidate.exists():
                return str(candidate), spec["label"]
        for exe in spec.get("app_paths", []):
            found = _find_in_app_paths(exe)
            if found:
                return found, spec["label"]
        for exe in spec.get("which", []):
            found = shutil.which(exe)
            if found:
                return found, spec["label"]
        shortcut = _find_in_start_menu(spec["label"]) or _find_in_start_menu(key or lowered)
        if shortcut:
            return shortcut, spec["label"]
        return None, spec["label"]

    # Unknown app: try direct executable lookup, then Start Menu.
    exe = raw if raw.lower().endswith(".exe") else f"{raw}.exe"
    found = shutil.which(exe) or shutil.which(raw) or _find_in_app_paths(exe)
    if found:
        return found, raw
    shortcut = _find_in_start_menu(raw)
    if shortcut:
        return shortcut, raw
    return None, raw


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
def _launch(target: str) -> None:
    """Start a resolved target. Uses an argument list, never a shell string."""
    if target.startswith("ms-") or target == "control":
        os.startfile(target)  # noqa: S606
        return
    if target in ("explorer", "new_terminal"):
        return
    if target.lower().endswith(".lnk"):
        os.startfile(target)  # noqa: S606
        return
    subprocess.Popen([target], close_fds=True)  # noqa: S603


def open_application(name: str, arguments: str = "") -> dict:
    """Launch a desktop application by name."""
    target, label = resolve_application(name)

    if target is None:
        return _err(
            f'I could not find "{name}" on this computer. Try the exact app name, '
            f"or tell me the full path to its .exe.",
            requested=name,
        )

    try:
        if target == "explorer":
            subprocess.Popen(["explorer.exe"], close_fds=True)  # noqa: S603
        elif target == "new_terminal":
            subprocess.Popen(["cmd.exe", "/c", "start", "cmd"], close_fds=True)  # noqa: S603
        elif target == "control":
            subprocess.Popen(["control.exe"], close_fds=True)  # noqa: S603
        elif target.startswith("ms-"):
            os.startfile(target)  # noqa: S606
        elif arguments:
            subprocess.Popen([target, *arguments.split()], close_fds=True)  # noqa: S603
        else:
            _launch(target)
    except OSError as exc:
        return _err(f'Windows refused to start "{label}": {exc}', requested=name)

    return _ok(f"Opened {label}.", app=label, target=target)


def open_folder(path: str = "") -> dict:
    """Open a folder in File Explorer."""
    if not path or path.strip() in (".", "~", ""):
        target = config.HOME
    else:
        target = safety.resolve_path(path, must_exist=True, allow_outside_home=True)

    if not target.is_dir():
        return _err(f'"{target}" is not a folder.')

    try:
        os.startfile(str(target))  # noqa: S606
    except OSError as exc:
        return _err(f'I could not open "{target}": {exc}')

    return _ok(f'Opened the folder "{target.name}" in File Explorer.', path=str(target))


def open_file(path: str) -> dict:
    """Open a file with its default Windows application."""
    target = safety.require_existing_file(path)

    executable = target.suffix.lower() in (".exe", ".bat", ".cmd", ".ps1", ".msi", ".reg", ".vbs", ".scr", ".com")
    if executable:
        return _err(
            f'"{target.name}" is an executable, so I will not launch it automatically.',
            path=str(target),
        )

    try:
        os.startfile(str(target))  # noqa: S606
    except OSError as exc:
        return _err(f'No application on this PC could open "{target.name}": {exc}')

    return _ok(f'Opened "{target.name}".', path=str(target))
