"""System information and tightly controlled command execution."""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .. import config
from . import safety


def _ok(message: str, **data) -> dict:
    return {"ok": True, "message": message, "data": data}


def _err(message: str, **data) -> dict:
    return {"ok": False, "message": message, "data": data}


# --------------------------------------------------------------------------- #
# Read-only information
# --------------------------------------------------------------------------- #
def _memory_gb() -> tuple[float, float]:
    """(total, available) physical memory in GB using the Win32 API."""
    try:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
            return stat.ullTotalPhys / 1024**3, stat.ullAvailPhys / 1024**3
    except Exception:  # noqa: BLE001
        pass
    return 0.0, 0.0


def _battery() -> dict | None:
    try:
        class POWER_STATUS(ctypes.Structure):
            _fields_ = [
                ("ACLineStatus", ctypes.c_ubyte),
                ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte),
                ("Reserved1", ctypes.c_ubyte),
                ("BatteryLifeTime", ctypes.c_ulong),
                ("BatteryFullLifeTime", ctypes.c_ulong),
            ]

        status = POWER_STATUS()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):  # type: ignore[attr-defined]
            if status.BatteryLifePercent == 255:
                return None
            return {
                "percent": status.BatteryLifePercent,
                "plugged": status.ACLineStatus == 1,
            }
    except Exception:  # noqa: BLE001
        pass
    return None


def system_info() -> dict:
    """Summary of the machine JARVIS is running on."""
    total_ram, free_ram = _memory_gb()
    try:
        disk = shutil.disk_usage(str(config.HOME))
        disk_total, disk_free = disk.total / 1024**3, disk.free / 1024**3
    except OSError:
        disk_total = disk_free = 0.0

    battery = _battery()
    data = {
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
        "ram_total_gb": round(total_ram, 1),
        "ram_free_gb": round(free_ram, 1),
        "disk_total_gb": round(disk_total, 1),
        "disk_free_gb": round(disk_free, 1),
        "python": platform.python_version(),
        "user": os.environ.get("USERNAME", "user"),
        "computer": platform.node(),
        "boot_time": datetime.fromtimestamp(time.time() - _uptime_seconds()).strftime("%Y-%m-%d %H:%M"),
    }
    if battery:
        data["battery_percent"] = battery["percent"]
        data["battery_plugged"] = battery["plugged"]

    return _ok("Here is your system status.", **data)


def _uptime_seconds() -> float:
    try:
        return ctypes.windll.kernel32.GetTickCount64() / 1000.0  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return 0.0


def get_time() -> dict:
    """Current local date and time."""
    now = datetime.now()
    return _ok(
        now.strftime("It is %I:%M %p on %A, %d %B %Y.").replace(" 0", " "),
        time=now.strftime("%H:%M"),
        date=now.strftime("%Y-%m-%d"),
        friendly=now.strftime("%A, %d %B %Y"),
        iso=now.isoformat(timespec="seconds"),
    )


def list_safe_commands() -> dict:
    """Show which diagnostic commands are allowed."""
    names = sorted(safety.SAFE_COMMANDS)
    return _ok("I can run these read-only diagnostics: " + ", ".join(names) + ".", commands=names)


# --------------------------------------------------------------------------- #
# Command execution (allow-list only)
# --------------------------------------------------------------------------- #
def run_command(command: str) -> dict:
    """
    Run a read-only diagnostic command from the allow-list.

    Anything not on the list is rejected outright - the router never forwards
    destructive shell strings here, and the safety layer double-checks.
    """
    verdict = safety.vet_command(command)
    if not verdict["ok"]:
        return _err(verdict["reason"], command=command)

    argv = verdict["argv"]
    try:
        completed = subprocess.run(  # noqa: S603
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=25,
            cwd=str(config.HOME),
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return _err(f'"{argv[0]}" took too long, so I stopped it.', command=command)
    except FileNotFoundError:
        return _err(f'"{argv[0]}" is not installed on this computer.', command=command)
    except OSError as exc:
        return _err(f'I could not run that command: {exc}', command=command)

    output = (completed.stdout or completed.stderr or "").strip()
    if len(output) > 4000:
        output = output[:4000] + "\n... (truncated)"

    if completed.returncode != 0 and not output:
        return _err(f'"{argv[0]}" exited with code {completed.returncode}.', command=command)

    return _ok(
        f'Ran "{command}".',
        command=command,
        exit_code=completed.returncode,
        output=output or "(no output)",
    )


# --------------------------------------------------------------------------- #
# Power actions (confirmation-gated by the registry)
# --------------------------------------------------------------------------- #
POWER_ACTIONS = {
    "lock": ("rundll32.exe", ["user32.dll,LockWorkStation"], "Locking your computer."),
    "sleep": ("rundll32.exe", ["powrprof.dll,SetSuspendState", "0,1,0"], "Putting the computer to sleep."),
    "shutdown": ("shutdown.exe", ["/s", "/t", "30"], "Shutting down in 30 seconds."),
    "restart": ("shutdown.exe", ["/r", "/t", "30"], "Restarting in 30 seconds."),
    "cancel": ("shutdown.exe", ["/a"], "Cancelling the pending power action."),
}


def system_power(action: str) -> dict:
    """Lock / sleep / shut down / restart the machine."""
    action = (action or "").strip().lower()
    if action not in POWER_ACTIONS:
        return _err(f'I do not know the power action "{action}". Use lock, sleep, shutdown or restart.')

    program, args, note = POWER_ACTIONS[action]
    try:
        subprocess.run([program, *args], shell=False, timeout=15, check=False)  # noqa: S603
    except OSError as exc:
        return _err(f'I could not {action} the computer: {exc}')

    return _ok(note, action=action)


def cancel_power() -> dict:
    """Cancel a pending shutdown/restart."""
    return system_power("cancel")


def show_desktop() -> dict:
    """Minimise everything and show the desktop."""
    try:
        ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)  # LWin down
        ctypes.windll.user32.keybd_event(0x44, 0, 0, 0)  # D down
        ctypes.windll.user32.keybd_event(0x44, 0, 2, 0)  # D up
        ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)  # LWin up
    except Exception as exc:  # noqa: BLE001
        return _err(f"I could not show the desktop: {exc}")
    return _ok("Showing the desktop.")


def open_task_manager() -> dict:
    try:
        subprocess.Popen(["taskmgr.exe"], close_fds=True)  # noqa: S603
    except OSError as exc:
        return _err(f"I could not open Task Manager: {exc}")
    return _ok("Opened Task Manager.")


def empty_recycle_bin() -> dict:
    """Permanently erase the recycle bin (confirmation-gated)."""
    try:
        result = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x7)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        return _err(f"I could not empty the recycle bin: {exc}")
    if result != 0:
        return _err("Windows reported that the recycle bin could not be emptied.")
    return _ok("Emptied the recycle bin.")


def disk_usage(path: str = "") -> dict:
    """Free space on a drive."""
    target = Path(path) if path else config.HOME
    if not target.exists():
        return _err(f'"{target}" does not exist.')
    while not target.exists() and target != target.parent:
        target = target.parent
    try:
        usage = shutil.disk_usage(str(target))
    except OSError as exc:
        return _err(f"I could not read that drive: {exc}")
    free = usage.free / 1024**3
    total = usage.total / 1024**3
    return _ok(
        f"{free:.1f} GB free of {total:.1f} GB.",
        path=str(target),
        free_gb=round(free, 1),
        total_gb=round(total, 1),
        used_percent=round(usage.used / usage.total * 100, 1),
    )
