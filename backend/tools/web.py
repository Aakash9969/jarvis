"""Browser / web tools."""

from __future__ import annotations

import webbrowser
from urllib.parse import quote_plus, urlparse

from . import safety
from .. import config

KNOWN_SITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com",
    "google maps": "https://maps.google.com",
    "maps": "https://maps.google.com",
    "github": "https://github.com",
    "stack overflow": "https://stackoverflow.com",
    "stackoverflow": "https://stackoverflow.com",
    "wikipedia": "https://www.wikipedia.org",
    "chatgpt": "https://chat.openai.com",
    "reddit": "https://www.reddit.com",
    "linkedin": "https://www.linkedin.com",
    "twitter": "https://twitter.com",
    "x": "https://twitter.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "netflix": "https://www.netflix.com",
    "amazon": "https://www.amazon.com",
    "whatsapp": "https://web.whatsapp.com",
    "spotify": "https://open.spotify.com",
    "notion": "https://www.notion.so",
    "canva": "https://www.canva.com",
}

SEARCH_ENGINES = {
    "google": "https://www.google.com/search?q={q}",
    "bing": "https://www.bing.com/search?q={q}",
    "duckduckgo": "https://duckduckgo.com/?q={q}",
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "github": "https://github.com/search?q={q}",
    "stackoverflow": "https://stackoverflow.com/search?q={q}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={q}",
    "amazon": "https://www.amazon.com/s?k={q}",
}

_ALLOWED_SCHEMES = ("http", "https")


def _ok(message: str, **data) -> dict:
    return {"ok": True, "message": message, "data": data}


def _err(message: str, **data) -> dict:
    return {"ok": False, "message": message, "data": data}


def normalise_url(url: str) -> str:
    raw = (url or "").strip().strip('"').strip("'")
    if not raw:
        raise ValueError("No address was given.")
    lowered = raw.lower()
    for bad in ("javascript:", "data:", "file:", "vbscript:", "about:"):
        if lowered.startswith(bad):
            raise ValueError("That kind of address is not safe for me to open.")
    if not lowered.startswith(("http://", "https://")):
        if raw.startswith("//"):
            raw = "https:" + raw
        else:
            raw = "https://" + raw.replace(" ", "%20")
    parsed = urlparse(raw)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.netloc:
        raise ValueError(f'"{url}" does not look like a web address.')
    if "." not in parsed.netloc and parsed.netloc != "localhost":
        raise ValueError(f'"{url}" does not look like a web address.')
    return raw


def open_url(url: str) -> dict:
    try:
        target = normalise_url(url)
    except ValueError as exc:
        return _err(str(exc))
    try:
        opened = webbrowser.open(target, new=2)
    except Exception as exc:
        return _err(f"I could not reach your browser: {exc}")
    if not opened:
        return _err("Your default browser would not open that address.")
    host = urlparse(target).netloc.replace("www.", "")
    return _ok(f"Opened {host} in your browser.", url=target)


def open_site(name: str) -> dict:
    key = (name or "").strip().lower()
    if key not in KNOWN_SITES:
        for known, site in KNOWN_SITES.items():
            if known in key:
                key = known
                break
    if key not in KNOWN_SITES:
        return _err(f'I do not have "{name}" saved as a site. Give me the full address and I will open it.')
    return open_url(KNOWN_SITES[key])


def search_web(query: str, engine: str = "google") -> dict:
    query = (query or "").strip()
    if not query:
        return _err("What should I search for?")
    engine = (engine or "google").strip().lower()
    template = SEARCH_ENGINES.get(engine)
    if not template:
        engine, template = "google", SEARCH_ENGINES["google"]
    url = template.format(q=quote_plus(query))
    result = open_url(url)
    if result["ok"]:
        result["message"] = f'Searching {engine.title()} for "{query}".'
        result["data"]["query"] = query
    return result


def download_file(url: str, filename: str = "") -> dict:
    """Download a file from a URL to the workspace/Downloads folder."""
    try:
        target_url = normalise_url(url)
    except ValueError as exc:
        return _err(str(exc))

    # Determine destination
    if not filename:
        # Extract from URL
        parsed = urlparse(target_url)
        filename = parsed.path.split("/")[-1] or "download"
    filename = safety.clean_name(filename)

    # Save to workspace or Downloads
    dest_dir = config.ensure_workspace() / "Downloads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename

    # Handle conflicts
    if dest_path.exists():
        base, ext = filename.rsplit(".", 1) if "." in filename else (filename, "")
        i = 1
        while True:
            new_name = f"{base} ({i})" + (f".{ext}" if ext else "")
            new_path = dest_dir / new_name
            if not new_path.exists():
                dest_path = new_path
                filename = new_name
                break
            i += 1

    try:
        import urllib.request
        urllib.request.urlretrieve(target_url, dest_path)
    except Exception as exc:
        return _err(f"Download failed: {exc}")

    return _ok(f'Downloaded "{filename}" to {dest_dir}.', path=str(dest_path), filename=filename)
