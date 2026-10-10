"""
JARVIS launcher.

    python run.py                 start the backend and open the UI
    python run.py --no-browser    start the backend only
    python run.py --port 9000     use a specific port

The UI opens in Edge or Chrome in "app mode" when available (a clean window
without browser chrome), otherwise in the default browser.
"""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend import config  # noqa: E402
from backend.server import serve  # noqa: E402


def find_free_port(start: int) -> int:
    for port in range(start, start + 40):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((config.HOST, port))
                return port
            except OSError:
                continue
    raise SystemExit(f"No free port found between {start} and {start + 40}.")


def create_desktop_shortcut(url: str) -> bool:
    """Create a desktop shortcut to launch JARVIS in app mode."""
    try:
        import winshell
        from win32com.client import Dispatch
    except ImportError:
        return False

    desktop = Path(winshell.desktop())
    shortcut_path = desktop / "JARVIS.lnk"
    
    # Point to the batch file which sets env vars
    bat_path = Path(__file__).resolve().parent / "start_jarvis.bat"
    
    shell = Dispatch('WScript.Shell')
    shortcut = shell.CreateShortCut(str(shortcut_path))
    shortcut.Targetpath = str(bat_path)
    shortcut.WorkingDirectory = str(Path(__file__).resolve().parent)
    shortcut.IconLocation = f"{sys.executable},0"
    shortcut.Description = "JARVIS Desktop Assistant"
    shortcut.save()
    return True


def open_ui(url: str) -> None:
    """Prefer a chromeless app window; fall back to the default browser."""
    candidates = [
        (r"{PROGRAMFILES}\Google\Chrome\Application\chrome.exe", "--app="),
        (r"{PROGRAMFILES(X86)}\Google\Chrome\Application\chrome.exe", "--app="),
        (r"{LOCALAPPDATA}\Google\Chrome\Application\chrome.exe", "--app="),
        (r"{PROGRAMFILES(X86)}\Microsoft\Edge\Application\msedge.exe", "--app="),
        (r"{PROGRAMFILES}\Microsoft\Edge\Application\msedge.exe", "--app="),
    ]
    import os

    for template, flag in candidates:
        path = Path(os.path.expandvars(template))
        if path.exists():
            try:
                subprocess.Popen(  # noqa: S603
                    [str(path), f"{flag}{url}", "--window-size=1280,860"],
                    close_fds=True,
                )
                return
            except OSError:
                continue

    edge = shutil.which("msedge")
    if edge:
        try:
            subprocess.Popen([edge, f"--app={url}", "--window-size=1280,860"], close_fds=True)  # noqa: S603
            return
        except OSError:
            pass

    webbrowser.open(url, new=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the JARVIS desktop assistant.")
    parser.add_argument("--port", type=int, default=None, help="port for the local backend")
    parser.add_argument("--no-browser", action="store_true", help="do not open the UI automatically")
    parser.add_argument("--create-shortcut", action="store_true", help="create desktop shortcut and exit")
    args = parser.parse_args()

    port = args.port or find_free_port(config.PORT)
    url = f"http://{config.HOST}:{port}/"

    # Create desktop shortcut if requested
    if args.create_shortcut:
        if create_desktop_shortcut(url):
            print("Desktop shortcut created: JARVIS.lnk")
        else:
            print("Could not create shortcut (winshell/pywin32 not installed)")
        return

    try:
        httpd = serve(config.HOST, port)
    except OSError as exc:
        raise SystemExit(f"Could not start the backend on port {port}: {exc}") from exc

    workspace = config.ensure_workspace()

    print()
    print("  " + "=" * 58)
    print("   J A R V I S   -   desktop assistant")
    print("  " + "=" * 58)
    print(f"   UI          : {url}")
    print(f"   Workspace   : {workspace}")
    print(f"   AI model    : {config.LLM_MODEL}")
    if config.LLM_API_KEY:
        print("   AI key      : found in the environment")
    else:
        print("   AI key      : not configured - running on the offline brain")
        print("                 set JARVIS_API_KEY (or OPENAI_API_KEY) to enable full AI")
    print("  " + "=" * 58)
    print("   Press Ctrl+C to stop.")
    print("   (Run with --create-shortcut to add a desktop icon)")
    print()

    if not args.no_browser:
        threading.Thread(target=lambda: (time.sleep(0.6), open_ui(url)), daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Shutting down JARVIS. Goodbye.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
