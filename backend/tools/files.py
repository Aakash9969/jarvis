"""File and folder tools. Every write is validated by ``safety`` first."""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

from . import safety

MAX_READ_CHARS = 20_000
MAX_WRITE_CHARS = 400_000


def _ok(message: str, **data) -> dict:
    return {"ok": True, "message": message, "data": data}


def _err(message: str, **data) -> dict:
    return {"ok": False, "message": message, "data": data}


def _stamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


# --------------------------------------------------------------------------- #
# create / write
# --------------------------------------------------------------------------- #
def create_folder(path: str) -> dict:
    """Create a folder (and any missing parents)."""
    target = safety.resolve_path(path, for_write=True)
    if target.exists():
        if target.is_dir():
            return _ok(f'The folder "{target.name}" already exists at {target}.', path=str(target), existed=True)
        return _err(f'There is already a file called "{target.name}" there.')

    target.mkdir(parents=True, exist_ok=True)
    return _ok(f'Created the folder "{target.name}" in {target.parent}.', path=str(target))


def create_file(path: str, content: str = "") -> dict:
    """Create a new file. Refuses to clobber an existing file."""
    target = safety.resolve_path(path, for_write=True)
    if target.exists():
        return _err(
            f'"{target.name}" already exists. Tell me to write into it if you want to replace its contents.',
            path=str(target),
            exists=True,
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    body = (content or "")
    if len(body) > MAX_WRITE_CHARS:
        return _err("That content is too large for me to write in one go.")
    target.write_text(body, encoding="utf-8")
    size = target.stat().st_size
    return _ok(f'Created "{target.name}" in {target.parent}.', path=str(target), size=size)


def write_file(path: str, content: str) -> dict:
    """Create or replace the contents of a file."""
    target = safety.resolve_path(path, for_write=True)
    body = content or ""
    if len(body) > MAX_WRITE_CHARS:
        return _err("That content is too large for me to write in one go.")

    existed = target.exists()
    if existed and target.is_dir():
        return _err(f'"{target.name}" is a folder, not a file.')

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    verb = "Updated" if existed else "Created"
    words = len(body.split())
    return _ok(
        f'{verb} "{target.name}" with {words} word{"s" if words != 1 else ""}.',
        path=str(target),
        size=target.stat().st_size,
    )


def append_file(path: str, content: str) -> dict:
    """Append text to a file, creating it when missing."""
    target = safety.resolve_path(path, for_write=True)
    body = content or ""
    if not body:
        return _err("I did not have any content to add.")

    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    with target.open("a", encoding="utf-8") as handle:
        if existed and target.stat().st_size > 0:
            handle.write("\n")
        else:
            header = f"# {target.stem} - updated {datetime.now():%Y-%m-%d %H:%M}\n\n"
            handle.write(header)
        handle.write(body.rstrip() + "\n")

    verb = "Added to" if existed else "Created and wrote"
    return _ok(f'{verb} "{target.name}".', path=str(target), size=target.stat().st_size)


# --------------------------------------------------------------------------- #
# read / list
# --------------------------------------------------------------------------- #
def read_file(path: str, max_chars: int = MAX_READ_CHARS) -> dict:
    """Read a text file."""
    target = safety.require_existing_file(path)
    if target.stat().st_size > 5_000_000:
        return _err(f'"{target.name}" is too large for me to read safely.')

    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return _err(f'I could not read "{target.name}": {exc}')

    truncated = len(text) > max_chars
    body = text[:max_chars]
    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    return _ok(
        f'Here is the content of "{target.name}".',
        path=str(target),
        content=body,
        lines=lines,
        truncated=truncated,
        size=target.stat().st_size,
    )


def list_files(path: str = ".") -> dict:
    """List the contents of a folder."""
    target = safety.resolve_path(path or ".", must_exist=True, allow_outside_home=True)
    if not target.is_dir():
        return _err(f'"{target}" is not a folder.')

    entries = []
    try:
        for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            try:
                size = child.stat().st_size if child.is_file() else None
                modified = _stamp(child)
            except OSError:
                size, modified = None, ""
            entries.append(
                {
                    "name": child.name,
                    "type": "folder" if child.is_dir() else "file",
                    "size": size,
                    "modified": modified,
                }
            )
            if len(entries) >= 200:
                break
    except PermissionError:
        return _err(f'Windows would not let me list "{target}".')

    folders = sum(1 for e in entries if e["type"] == "folder")
    files = len(entries) - folders
    return _ok(
        f'"{target.name}" contains {folders} folder{"s" if folders != 1 else ""} and '
        f'{files} file{"s" if files != 1 else ""}.',
        path=str(target),
        entries=entries,
    )


# --------------------------------------------------------------------------- #
# move / delete  (confirmation-gated by the registry)
# --------------------------------------------------------------------------- #
def move_path(source: str, destination: str) -> dict:
    """Move a file or folder."""
    src = safety.resolve_path(source, for_write=True, must_exist=True)
    dst_raw = safety.resolve_path(destination, for_write=True)

    if dst_raw.exists() and dst_raw.is_dir():
        dst = dst_raw / src.name
    else:
        dst = dst_raw

    if dst.exists():
        return _err(f'"{dst.name}" already exists there, so I did not overwrite it.')

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return _ok(f'Moved "{src.name}" to {dst.parent}.', path=str(dst))


def delete_path(path: str) -> dict:
    """Delete a file, or a folder and everything inside it."""
    target = safety.resolve_path(path, for_write=True, must_exist=True)

    if target.parent == target:
        return _err("I will not delete a drive root.")

    if target.is_dir():
        count = sum(1 for _ in target.rglob("*"))
        shutil.rmtree(target)
        return _ok(f'Deleted the folder "{target.name}" and {count} item(s) inside it.', path=str(target))

    name = target.name
    size = target.stat().st_size
    target.unlink()
    return _ok(f'Deleted the file "{name}".', path=str(target), size=size)


def path_info(path: str) -> dict:
    """Describe a path without changing it."""
    target = safety.resolve_path(path, must_exist=True, allow_outside_home=True)
    stat = target.stat()
    return _ok(
        f'"{target.name}" is a {"folder" if target.is_dir() else "file"}, '
        f'{stat.st_size} bytes, last changed {_stamp(target)}.',
        path=str(target),
        is_dir=target.is_dir(),
        size=stat.st_size,
        modified=_stamp(target),
    )


def reveal_in_explorer(path: str) -> dict:
    """Open Windows Explorer with the item selected."""
    target = safety.resolve_path(path, must_exist=True, allow_outside_home=True)
    if target.is_dir():
        os.startfile(str(target))  # noqa: S606 - validated path, Explorer only
    else:
        os.system(f'explorer /select,"{target}"')
    return _ok(f'Showing "{target.name}" in File Explorer.', path=str(target))
