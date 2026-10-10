"""
Offline brain.

A deterministic, structured intent router. It produces exactly the same
``{"tool": ..., "args": ...}`` calls that the online LLM produces through
function calling, so the agent does not care which brain answered.

It also serves as a fallback conversational engine when no LLM key is
configured, using a bundled knowledge base plus safe arithmetic.
"""

from __future__ import annotations

import ast
import math
import os
import re
from pathlib import Path

from . import config, generators, memory as memory_module
from .tools import safety, web

# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _clean(text: str) -> str:
    text = (text or "").strip()
    # Only strip "jarvis" when it is used as a vocative at the start - never
    # inside a path (the workspace folder is literally called JARVIS).
    text = re.sub(r"^(?:hey|hi|hello|ok|okay|yo|dear)\s+jarvis\b[,]?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*jarvis\b[,]?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(please|can you|could you|would you|i want you to|i need you to)\s+", "", text, flags=re.IGNORECASE)
    text = text.strip().rstrip("?.!")
    return text


def _strip_article(text: str) -> str:
    return re.sub(r"^(a|an|the)\s+", "", text.strip(), flags=re.IGNORECASE).strip()


KNOWN_FOLDERS = {
    "documents": config.DOCUMENTS,
    "document": config.DOCUMENTS,
    "my documents": config.DOCUMENTS,
    "downloads": config.DOWNLOADS,
    "my downloads": config.DOWNLOADS,
    "desktop": config.DESKTOP,
    "my desktop": config.DESKTOP,
    "home": config.HOME,
    "home folder": config.HOME,
    "user folder": config.HOME,
    "workspace": config.WORKSPACE,
    "jarvis workspace": config.WORKSPACE,
    "jarvis folder": config.WORKSPACE,
    "jarvis": config.WORKSPACE,
    "my workspace": config.WORKSPACE,
    "pictures": config.HOME / "Pictures",
    "music": config.HOME / "Music",
    "videos": config.HOME / "Videos",
    "this pc": "::{20D04FE0-3AEA-1069-A2D8-08002B30309D}",
}

_EXTENSION = re.compile(r"\.(txt|md|markdown|py|js|ts|json|csv|html|css|java|c|cpp|cs|sql|xml|yml|yaml|log|ini|cfg|bat|ps1|tex|rtf|docx?|xlsx?|pptx?|pdf)\b", re.IGNORECASE)
_FILE_LIKE = re.compile(r"[^\\/\s]+\.[A-Za-z0-9]{1,6}$")


def _resolve_target(raw: str) -> Path | None:
    """Best-effort check whether a name points at something real."""
    text = (raw or "").strip().strip('"').strip("'")
    if not text:
        return None

    lowered = text.lower()
    if lowered in KNOWN_FOLDERS and isinstance(KNOWN_FOLDERS[lowered], Path):
        return KNOWN_FOLDERS[lowered]

    try:
        candidate = Path(os.path.expandvars(text)).expanduser()
        if candidate.is_absolute():
            return candidate if candidate.exists() else None
        for base in (config.ensure_workspace(), config.HOME, Path.cwd()):
            probe = base / candidate
            if probe.exists():
                return probe
    except (OSError, ValueError):
        return None
    return None


def _looks_like_file(name: str) -> bool:
    return bool(_EXTENSION.search(name)) or bool(_FILE_LIKE.search(name or ""))


def _starter(name: str) -> str:
    """A minimal starter body for freshly created code files."""
    lowered = name.lower()
    if lowered.endswith(".py"):
        return f"# {name}\n# Created by JARVIS\n\n\ndef main():\n    print(\"Hello from {name}\")\n\n\nif __name__ == \"__main__\":\n    main()\n"
    if lowered.endswith((".js", ".ts")):
        return f"// {name}\n// Created by JARVIS\n\nconsole.log(\"Hello from {name}\");\n"
    if lowered.endswith((".html", ".htm")):
        return ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n  <meta charset=\"utf-8\">\n"
                f"  <title>{name}</title>\n</head>\n<body>\n  <h1>{name}</h1>\n</body>\n</html>\n")
    if lowered.endswith(".sql"):
        return f"-- {name}\n-- Created by JARVIS\n\nSELECT 1;\n"
    return ""


# --------------------------------------------------------------------------- #
# Confirmation words
# --------------------------------------------------------------------------- #
YES_WORDS = {
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed",
    "do it", "go ahead", "proceed", "please do", "affirmative", "yes please",
    "i confirm", "approve", "approved", "allow it", "yes do it", "ja",
}
NO_WORDS = {
    "no", "nope", "nah", "cancel", "stop", "don't", "dont", "abort", "never mind",
    "nevermind", "forget it", "deny", "reject", "no thanks", "no thank you",
    "leave it", "do not", "negative",
}


def confirmation_intent(text: str) -> str | None:
    cleaned = _clean(text).lower().strip(" .!,")
    if cleaned in YES_WORDS:
        return "yes"
    if cleaned in NO_WORDS:
        return "no"
    if re.fullmatch(r"(yes|yeah|yep|ok|okay|sure)[,\s]+(do it|go ahead|proceed|please)", cleaned):
        return "yes"
    return None


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
def route(text: str, memory: memory_module.Memory) -> dict:
    """
    Classify *text*.

    Returns one of::

        {"kind": "tool", "tool": "<name>", "args": {...}, "note": "..."}
        {"kind": "chat", "reply": "..."}
    """
    original = (text or "").strip()
    cleaned = _clean(original)
    lowered = cleaned.lower()

    if not cleaned:
        return {"kind": "chat", "reply": "I did not catch that. Could you say it again?"}

    # ---- meta ---------------------------------------------------------- #
    if re.fullmatch(r"(help|what can you do|what can you do\?|commands|what can i say|capabilities)", lowered):
        return {"kind": "chat", "reply": _HELP}

    if re.fullmatch(r"(reset|clear|clear chat|clear conversation|start over|forget everything)", lowered):
        return {"kind": "reset"}

    # ---- 1. write / append ---------------------------------------------- #
    # Runs before the "create" patterns so that "add a note to it" appends
    # instead of being mistaken for a file creation.
    match = re.match(
        r"(?:write|save|put|store|append|add)\s+(?P<content>.+?)\s+(?:in|into|to|inside)\s+(?P<path>.+)$",
        cleaned,
        re.IGNORECASE,
    )
    if match and not re.match(r"^(open|launch|start)\b", lowered):
        content_text = match.group("content").strip().strip('"').strip("'")
        path_text = match.group("path").strip().strip('"').strip("'")
        looks_like_creation = re.match(r"^(a|an|the|new)\s+(file|folder|document|doc|note|notes|script)\b", content_text, re.IGNORECASE)
        if path_text and content_text and not looks_like_creation:
            path_text = _ensure_extension(path_text, lowered)
            quoted = bool(re.search(r'["\']', match.group("content")))
            kind, generated = generators.generate_content(content_text, filename=path_text)
            content = generated if (kind != "document" and not quoted) else content_text
            tool = "append_file" if re.match(r"^(add|append)\b", lowered) else "write_file"
            return _tool(tool, {"path": path_text, "content": content}, f'writing into "{path_text}"')

    # ---- 2. file & folder creation --------------------------------------- #
    match = re.match(
        r"(?:create|make|new|add)\s+(?:a\s+|an\s+)?(?:new\s+)?(folder|directory|dir)\b\s*(?:called|named|as|:)?\s*(?P<path>.+)$",
        lowered,
    )
    if match:
        name = _extract_path_text(cleaned, match)
        if name:
            return _tool("create_folder", {"path": name}, f'creating the folder "{name}"')

    match = re.match(
        r"(?:create|make|new|generate|add)\s+(?:a\s+|an\s+)?(?:new\s+)?"
        r"(?P<desc>[\w\s\-]{0,40}?)\s*"
        r"(file|document|doc|script|note|notebook)\b\s*(?:called|named|as|:)?\s*(?P<path>.+)$",
        lowered,
    )
    if match:
        name = _extract_path_text(cleaned, match)
        if name:
            name = _ensure_extension(name, lowered)
            kind, content = generators.generate_content(lowered, filename=name)
            if kind == "document":
                content = _starter(name)
            return _tool(
                "create_file",
                {"path": name, "content": content},
                f'creating "{name}"',
            )

    # "create notes.txt" / "new test.py" (no keyword)
    match = re.match(r"(?:create|make|new|touch)\s+(?P<path>[^\s]+\.\w{1,6})$", lowered)
    if match:
        name = _extract_path_text(cleaned, match)
        kind, content = generators.generate_content(lowered, filename=name)
        return _tool(
            "create_file",
            {"path": name, "content": content if kind != "document" else _starter(name)},
            f'creating "{name}"',
        )

    # ---- 3. read / list -------------------------------------------------- #
    match = re.match(r"(?:read|show|display|view|print)\s+(?:me\s+)?(?:the\s+)?(?:content(?:s)?\s+of\s+|file\s+|contents?\s+of\s+)?(?P<path>[^\s].*)$", cleaned, re.IGNORECASE)
    if match and _looks_like_file(match.group("path")):
        path_text = _clean_path(match.group("path"))
        return _tool("read_file", {"path": path_text}, f'reading "{path_text}"')

    match = re.match(
        r"(?:list|show)\s+(?:me\s+)?(?:the\s+|all\s+)?(?:files|contents|everything|items)\s*(?:in|of|inside)?\s*(?P<path>.*)$",
        cleaned,
        re.IGNORECASE,
    )
    if match:
        path_text = _clean_path(match.group("path")) or "."
        known = _known_folder(path_text)
        if known:
            path_text = str(known)
        return _tool("list_files", {"path": path_text}, f'listing "{path_text}"')

    if re.match(r"^list\b", lowered):
        match = re.match(r"list\s+(?:me\s+)?(?:the\s+|all\s+|my\s+)?(?P<path>[\w .\-/\\:]+?)(?:\s+folder)?$", cleaned, re.IGNORECASE)
        if match:
            path_text = _clean_path(match.group("path")) or "."
            known = _known_folder(path_text)
            if known:
                path_text = str(known)
            return _tool("list_files", {"path": path_text}, f'listing "{path_text}"')

    match = re.match(r"(?:what(?:'s| is)?|whats)\s+(?:in|inside)\s+(?P<path>.+)$", cleaned, re.IGNORECASE)
    if match:
        path_text = _clean_path(match.group("path"))
        if _looks_like_file(path_text):
            return _tool("read_file", {"path": path_text}, f'reading "{path_text}"')
        known = _known_folder(path_text)
        if known:
            path_text = str(known)
        return _tool("list_files", {"path": path_text or "."}, f'listing "{path_text}"')

    # ---- 4. delete / move ------------------------------------------------ #
    match = re.match(r"(?:delete|remove|erase|bin)\s+(?:the\s+)?(?:file\s+|folder\s+|directory\s+)?(?P<path>.+)$", cleaned, re.IGNORECASE)
    if match:
        path_text = _clean_path(match.group("path"))
        if path_text:
            return _tool("delete_path", {"path": path_text}, f'deleting "{path_text}"')

    match = re.match(r"(?:move|rename)\s+(?:the\s+)?(?:file\s+|folder\s+)?(?P<src>.+?)\s+(?:to|into)\s+(?P<dst>.+)$", cleaned, re.IGNORECASE)
    if match:
        src = _clean_path(match.group("src"))
        dst = _clean_path(match.group("dst"))
        if src and dst:
            return _tool("move_path", {"source": src, "destination": dst}, f'moving "{src}" to "{dst}"')

    # ---- 5. diagnostics & apps ------------------------------------------- #
    if re.match(r"^(open|launch|start|show)\b", lowered) and re.search(r"\btask manager\b", lowered):
        return _tool("open_task_manager", {}, "opening Task Manager")

    # "run ipconfig" must reach the command tool; "run chrome" must not.
    match = re.match(r"^(?:run|execute)\s+(?:the\s+)?(?:command\s+|cmd\s+)?(?P<cmd>.+)$", cleaned, re.IGNORECASE)
    if match:
        candidate = match.group("cmd").strip().strip('"').strip("'")
        head = (candidate.split()[0].lower() if candidate.split() else "")
        if head.endswith(".exe"):
            head = head[:-4]
        if head in safety.SAFE_COMMANDS:
            return _tool("run_command", {"command": candidate}, f'running "{candidate}"')

    match = re.match(r"(?:open|launch|start|run|go to|navigate to|take me to|show me)\s+(?P<target>.+)$", cleaned, re.IGNORECASE)
    if match:
        target = _strip_article(match.group("target").strip().strip('"').strip("'"))
        decision = _decide_open(target, memory)
        if decision:
            return decision

    # ---- 6. search ------------------------------------------------------- #
    match = re.match(r"(?:search|google|look up|lookup|find|browse)\s+(?:for\s+)?(?:me\s+)?(?P<rest>.+)$", cleaned, re.IGNORECASE)
    if match:
        rest = match.group("rest").strip()
        engine = "google"
        site_match = re.match(r"(?P<engine>youtube|google|bing|duckduckgo|github|wikipedia|amazon|stackoverflow|stack overflow)\s+(?:for|about)\s+(?P<query>.+)$", rest, re.IGNORECASE)
        if site_match:
            engine = site_match.group("engine").lower().replace("stack overflow", "stackoverflow")
            query = site_match.group("query")
        else:
            on_match = re.match(r"(?P<query>.+?)\s+(?:on|in)\s+(?P<engine>youtube|google|bing|github|wikipedia|amazon)$", rest, re.IGNORECASE)
            if on_match:
                query = on_match.group("query")
                engine = on_match.group("engine").lower()
            else:
                query = re.sub(r"^(for|about)\s+", "", rest, flags=re.IGNORECASE)
        if query:
            return _tool("search_web", {"query": query, "engine": engine}, f"searching {engine} for \"{query}\"")

    # ---- 7. URL ---------------------------------------------------------- #
    match = re.match(r"(?:open|go to|visit)\s+(?P<url>(?:https?://|www\.)\S+)$", cleaned, re.IGNORECASE)
    if match:
        return _tool("open_url", {"url": match.group("url")}, "opening that address")

    # ---- 8. system ------------------------------------------------------- #
    if re.search(r"\b(what time|the time|current time|what's the time)\b", lowered):
        return _tool("get_time", {}, "checking the time")
    if re.search(r"\b(what('s| is)? (the )?date|today'?s date|what day is it)\b", lowered):
        return _tool("get_time", {}, "checking the date")

    if re.search(r"\b(system info|system status|system information|pc status|computer status|how'?s? my (pc|computer|system)|specs|battery)\b", lowered):
        return _tool("system_info", {}, "reading system status")

    if re.search(r"\b(disk space|free space|storage|hard drive space|drive space)\b", lowered):
        return _tool("disk_usage", {}, "checking disk space")

    if re.search(r"\b(show desktop|minimi[sz]e everything|minimi[sz]e all|show me the desktop)\b", lowered):
        return _tool("show_desktop", {}, "showing the desktop")

    if re.search(r"\b(open )?task manager\b", lowered):
        return _tool("open_task_manager", {}, "opening Task Manager")

    if re.search(r"\b(empty|clear|wipe)\b.*\brecycle bin\b", lowered):
        return _tool("empty_recycle_bin", {}, "emptying the Recycle Bin")

    if re.search(r"\b(safe commands|allowed commands|which commands can you run)\b", lowered):
        return _tool("list_safe_commands", {}, "listing allowed commands")

    power = _power_intent(lowered)
    if power:
        return power

    # ---- 9. math --------------------------------------------------------- #
    math_result = try_math(cleaned)
    if math_result is not None:
        return {"kind": "chat", "reply": math_result}

    # ---- 10. knowledge / chat -------------------------------------------- #
    return {"kind": "chat", "reply": answer_question(cleaned)}


def _tool(name: str, args: dict, note: str) -> dict:
    return {"kind": "tool", "tool": name, "args": args, "note": note}


def _extract_path_text(original: str, match: re.Match) -> str:
    """Recover the path from the *original* (case preserved) string."""
    group = match.groupdict().get("path")
    if not group:
        return ""
    raw = match.group(0)
    index = original.lower().find(group.lower())
    if index == -1:
        return _clean_path(group)
    return _clean_path(original[index:])


def _clean_path(text: str) -> str:
    text = (text or "").strip().strip('"').strip("'").strip()
    text = re.sub(r"\s+(please|thanks|thank you)$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(the|my)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(about|on|for|regarding|re:?)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(folder|directory|dir)$", "", text, flags=re.IGNORECASE)
    return text.strip()


def _known_folder(name: str):
    """Map a spoken folder name to a real path when we know it."""
    key = (name or "").strip().lower()
    key = re.sub(r"^(the|my)\s+", "", key)
    key = re.sub(r"\s+(folder|directory|dir)$", "", key)
    value = KNOWN_FOLDERS.get(key)
    return value if isinstance(value, Path) else None


def _ensure_extension(name: str, lowered: str) -> str:
    if _looks_like_file(name):
        return name
    hint = ""
    if "python" in lowered or "script" in lowered:
        hint = ".py"
    elif "json" in lowered:
        hint = ".json"
    elif "markdown" in lowered or name.lower().endswith(".md"):
        hint = ".md"
    elif "csv" in lowered:
        hint = ".csv"
    elif "html" in lowered:
        hint = ".html"
    elif "sql" in lowered:
        hint = ".sql"
    return name + (hint or ".txt")


def _decide_open(target: str, memory: memory_module.Memory) -> dict | None:
    """Work out the best 'open X' interpretation."""
    if not target:
        return None
    lowered = target.lower().strip()

    # explicit URL
    if re.match(r"^(https?://|www\.)\S+$", lowered):
        return _tool("open_url", {"url": target}, "opening that address")

    # domain-like ("github.com")
    if re.fullmatch(r"[\w-]+\.[a-z]{2,}(?:/\S*)?", lowered) and lowered not in web.KNOWN_SITES:
        return _tool("open_url", {"url": target}, f"opening {target}")

    # known website
    site_key = lowered.replace("website", "").replace("site", "").strip()
    if site_key in web.KNOWN_SITES:
        return _tool("open_site", {"name": site_key}, f"opening {site_key}")

    # known folder
    if lowered in KNOWN_FOLDERS:
        value = KNOWN_FOLDERS[lowered]
        return _tool("open_folder", {"path": str(value)}, f"opening {lowered}")

    folderish = re.match(r"^(?:the\s+|my\s+)?(?P<name>.+?)\s+(?:folder|directory)$", lowered)
    if folderish:
        name = folderish.group("name").strip()
        if name in KNOWN_FOLDERS:
            return _tool("open_folder", {"path": str(KNOWN_FOLDERS[name])}, f"opening {name}")
        return _tool("open_folder", {"path": name}, f'opening the folder "{name}"')

    # a real file / folder on disk
    real = _resolve_target(target)
    if real is not None:
        if real.is_dir():
            return _tool("open_folder", {"path": str(real)}, f'opening the folder "{real.name}"')
        return _tool("open_file", {"path": str(real)}, f'opening "{real.name}"')

    # file-ish name that does not exist yet
    if _looks_like_file(lowered):
        return _tool("open_file", {"path": target}, f'opening "{target}"')

    # otherwise treat it as an application
    return _tool("open_application", {"name": target}, f"opening {target}")


def _power_intent(lowered: str) -> dict | None:
    if re.search(r"\b(shut ?down|power off|power down|turn off (the )?(pc|computer|laptop))\b", lowered):
        return _tool("system_power", {"action": "shutdown"}, "shutting the computer down")
    if re.search(r"\b(restart|reboot)\b", lowered):
        return _tool("system_power", {"action": "restart"}, "restarting the computer")
    if re.search(r"\b(put .*to sleep|go to sleep|sleep mode|hibernate|suspend)\b", lowered):
        return _tool("system_power", {"action": "sleep"}, "putting the computer to sleep")
    if re.search(r"\block\b.*\b(pc|computer|screen|workstation|windows)\b", lowered) or lowered in ("lock", "lock pc", "lock computer", "lock screen"):
        return _tool("system_power", {"action": "lock"}, "locking the computer")
    if re.search(r"\bcancel\b.*\b(shut ?down|restart|power off)\b", lowered):
        return _tool("system_power", {"action": "cancel"}, "cancelling the pending power action")
    return None


# --------------------------------------------------------------------------- #
# Safe arithmetic
# --------------------------------------------------------------------------- #
_ALLOWED_FUNCS = {
    "sqrt": math.sqrt, "abs": abs, "round": round, "pow": pow,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "log": math.log, "log10": math.log10, "exp": math.exp, "floor": math.floor, "ceil": math.ceil,
}
_ALLOWED_NAMES = {"pi": math.pi, "e": math.e}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp):
        left, right = _eval_node(node.left), _eval_node(node.right)
        operations = {
            ast.Add: lambda a, b: a + b,
            ast.Sub: lambda a, b: a - b,
            ast.Mult: lambda a, b: a * b,
            ast.Div: lambda a, b: a / b,
            ast.FloorDiv: lambda a, b: a // b,
            ast.Mod: lambda a, b: a % b,
            ast.Pow: lambda a, b: a ** b,
        }
        operation = operations.get(type(node.op))
        if operation is None:
            raise ValueError("unsupported operator")
        if isinstance(node.op, ast.Pow) and abs(right) > 64:
            raise ValueError("exponent too large")
        return operation(left, right)
    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
        raise ValueError("unsupported operator")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
            raise ValueError("unsupported function")
        return _ALLOWED_FUNCS[node.func.id](*[_eval_node(a) for a in node.args])
    if isinstance(node, ast.Name):
        if node.id in _ALLOWED_NAMES:
            return _ALLOWED_NAMES[node.id]
        raise ValueError("unknown name")
    raise ValueError("unsupported expression")


def try_math(text: str) -> str | None:
    candidate = text.lower()
    candidate = re.sub(r"^(what(?:'s| is)|calculate|compute|solve|evaluate|how much is)\s+", "", candidate)
    candidate = candidate.replace("×", "*").replace("÷", "/").replace("^", "**")
    candidate = candidate.strip().rstrip("?= ").strip()
    if not candidate or len(candidate) > 80:
        return None
    if not re.fullmatch(r"[0-9+\-*/%().\s,]*(sqrt|abs|round|pow|sin|cos|tan|log10|log|exp|floor|ceil|pi|e)?[0-9+\-*/%().\s,]*", candidate):
        return None
    if not re.search(r"\d", candidate) or not re.search(r"[+\-*/%]", candidate):
        return None

    candidate = candidate.replace(",", "")
    try:
        value = _eval_node(ast.parse(candidate, mode="eval"))
    except Exception:  # noqa: BLE001
        return None

    if isinstance(value, float):
        if value.is_integer():
            pretty = f"{int(value):,}"
        else:
            pretty = f"{value:,.6f}".rstrip("0").rstrip(".")
    else:
        pretty = f"{value:,}"
    return f"That is {pretty}."


# --------------------------------------------------------------------------- #
# Knowledge base & conversational answers
# --------------------------------------------------------------------------- #
_KNOWLEDGE: dict[str, str] = {
    "python": "Python is a high-level, interpreted programming language known for readable syntax. "
              "It is dynamically typed, has automatic memory management, and ships with a large standard library. "
              "It is widely used for scripting, data science, web backends, automation and AI. "
              "Example:\n\n```python\nfor i in range(3):\n    print(i)\n```",
    "recursion": "Recursion is when a function calls itself to solve a smaller version of the same problem. "
                 "Every recursive function needs a base case that stops the recursion, and a recursive case that "
                 "moves toward the base case. Classic examples are factorial, Fibonacci and tree traversal.\n\n"
                 "```python\ndef factorial(n):\n    return 1 if n <= 1 else n * factorial(n - 1)\n```",
    "binary tree": "A binary tree is a tree data structure where each node has at most two children, called the left "
                   "and right child. In a binary search tree the left subtree holds smaller values and the right "
                   "subtree larger ones, which gives O(log n) search on a balanced tree. Traversals: in-order, "
                   "pre-order, post-order and level-order.",
    "binary search": "Binary search finds a value in a *sorted* array by repeatedly halving the search range. "
                     "It compares the target with the middle element and discards the half that cannot contain it. "
                     "Time complexity is O(log n).\n\n```python\ndef binary_search(a, target):\n    lo, hi = 0, len(a) - 1\n"
                     "    while lo <= hi:\n        mid = (lo + hi) // 2\n        if a[mid] == target:\n            return mid\n"
                     "        if a[mid] < target:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return -1\n```",
    "dbms": "A DBMS (Database Management System) is software that stores, retrieves and manages data while handling "
            "concurrency, transactions and security. Core ideas to study: the relational model, keys, normalisation "
            "(1NF to 3NF/BCNF), SQL, transactions and ACID, indexing (B-trees), and concurrency control such as "
            "two-phase locking. Popular systems: PostgreSQL, MySQL, SQL Server, Oracle and SQLite.",
    "normalization": "Normalisation organises tables to reduce redundancy and update anomalies: 1NF removes repeating "
                     "groups, 2NF removes partial dependencies on a composite key, 3NF removes transitive dependencies, "
                     "and BCNF tightens 3NF further.",
    "sql": "SQL (Structured Query Language) is the standard language for relational databases. Core commands: "
           "SELECT, INSERT, UPDATE, DELETE for data; CREATE, ALTER, DROP for structure; JOIN for combining tables; "
           "GROUP BY with aggregate functions for summaries.\n\n"
           "```sql\nSELECT dept, COUNT(*) FROM students GROUP BY dept;\n```",
    "oop": "Object-oriented programming organises code around objects that combine state (attributes) and behaviour "
           "(methods). The four pillars are encapsulation, abstraction, inheritance and polymorphism. Python example:\n\n"
           "```python\nclass Dog:\n    def __init__(self, name):\n        self.name = name\n\n    def speak(self):\n"
           "        return f\"{self.name} says woof\"\n```",
    "linked list": "A linked list is a linear structure where each node stores a value and a pointer to the next node. "
                   "Unlike arrays it grows in O(1) at the head and never needs reallocation, but random access costs "
                   "O(n). Variants: singly, doubly and circular linked lists.",
    "stack": "A stack is a last-in-first-out (LIFO) structure with push and pop. Uses: function call stacks, undo "
             "history, expression evaluation and backtracking. A queue is first-in-first-out (FIFO) with enqueue and "
             "dequeue, used in scheduling and breadth-first search.",
    "queue": "A queue is a first-in-first-out (FIFO) structure with enqueue and dequeue operations. It is used for "
             "scheduling, buffering and breadth-first search. A priority queue returns the smallest or largest item first.",
    "hash table": "A hash table stores key-value pairs in buckets chosen by a hash function, giving average O(1) "
                  "lookup, insert and delete. Collisions are handled by chaining or open addressing. Worst case is "
                  "O(n) if the hash function degrades.",
    "big o": "Big-O notation describes how an algorithm's cost grows with input size, ignoring constants. Common "
             "orders from fast to slow: O(1), O(log n), O(n), O(n log n), O(n^2), O(2^n), O(n!). Sorting with "
             "merge sort is O(n log n); binary search is O(log n); nested loops over the same array are O(n^2).",
    "time complexity": "Time complexity measures how runtime scales with input size, expressed with Big-O. Space "
                       "complexity does the same for memory. Always state the case you mean: best, average or worst.",
    "operating system": "An operating system manages hardware and provides services to programs: process scheduling, "
                        "memory management, file systems, device drivers, and security. Key theory topics: processes "
                        "vs threads, scheduling algorithms, deadlock, paging and virtual memory.",
    "machine learning": "Machine learning is the field of fitting models to data so they generalise to new inputs. "
                        "Main branches: supervised learning (labelled data), unsupervised learning (structure in "
                        "unlabelled data), and reinforcement learning (learning from rewards). Study order: "
                        "linear regression, logistic regression, regularisation, trees, ensembles, neural networks.",
    "artificial intelligence": "Artificial intelligence is the broad goal of making machines perform tasks that need "
                              "intelligence: reasoning, perception, language and planning. Subfields include search, "
                              "knowledge representation, machine learning, NLP, robotics and computer vision.",
    "api": "An API (Application Programming Interface) is a contract that lets one program call another. A web API "
           "usually exposes HTTP endpoints such as GET /users/42 that return JSON. REST organises these around "
           "resources; GraphQL and gRPC are common alternatives.",
    "http": "HTTP is the request/response protocol of the web. A request has a method (GET, POST, PUT, DELETE), a "
            "path, headers and an optional body. Responses carry a status code: 2xx success, 3xx redirect, 4xx client "
            "error, 5xx server error.",
    "json": 'JSON (JavaScript Object Notation) is a text format for structured data: objects in braces, arrays in '
            'brackets, and values that are strings, numbers, booleans or null. Example: {"name": "Asha", "age": 21}.',
    "git": "Git is a distributed version control system. Core workflow: `git init`, `git add`, `git commit`, "
           "`git branch`, `git checkout`, `git merge`, `git pull`, `git push`. Commits form a graph, and branches "
           "are just movable pointers into it.",
    "javascript": "JavaScript is the language of the web. It is dynamically typed and event-driven, with prototypal "
                  "inheritance and first-class functions. Modern syntax adds `let`/`const`, arrow functions, promises "
                  "and async/await, modules, and classes. It runs in browsers and on servers via Node.js.",
    "html": "HTML describes the structure of a web page with elements such as <h1>, <p>, <a> and <div>. CSS styles "
            "those elements, and JavaScript adds behaviour. Semantic elements and accessibility matter for real sites.",
    "css": "CSS controls presentation: colours, spacing, layout and animation. Modern layout uses Flexbox and Grid. "
           "Responsive design uses relative units and media queries. Animation uses transitions, keyframes, or "
           "spring physics from libraries such as Motion.",
    "react": "React is a JavaScript library for building user interfaces from reusable components with declarative "
             "state. Hooks such as useState and useEffect manage state and side effects. Motion for React animates "
             "components on mount, unmount and gesture.",
    "database": "A database stores organised data so it can be queried efficiently. Relational databases use tables "
                "and SQL; NoSQL systems include document stores (MongoDB), key-value stores (Redis), and graph "
                "databases (Neo4j).",
    "compiler": "A compiler translates source code into machine code in phases: lexical analysis, parsing, semantic "
                "analysis, intermediate representation, optimisation and code generation. An interpreter executes "
                "source directly, and a just-in-time compiler mixes both approaches.",
    "deadlock": "A deadlock is a state where processes wait on each other forever. It needs four conditions at once: "
                "mutual exclusion, hold and wait, no preemption, and circular wait. Handle it by prevention, "
                "avoidance (Banker's algorithm), detection with rollback, or simply ignoring it.",
    "process vs thread": "A process has its own address space; threads share their process's memory. Threads are "
                         "cheaper to create and communicate between, but need synchronisation (mutexes, semaphores) "
                         "to avoid race conditions.",
    "encryption": "Encryption converts readable data into ciphertext using a key. Symmetric algorithms (AES) use one "
                  "shared key and are fast; asymmetric ones (RSA, ECC) use a public/private key pair and enable key "
                  "exchange and signatures. Hashing (SHA-256) is one-way and used for integrity, not secrecy.",
    "networking": "Computer networking links devices so they can exchange data. Key models: OSI's seven layers and "
                  "TCP/IP's four. Study TCP vs UDP, IP addressing and subnetting, DNS, HTTP, and routing.",
}

_GREETINGS = re.compile(r"^(hi|hello|hey|yo|good (morning|afternoon|evening)|greetings|namaste|hola)$", re.IGNORECASE)
_THANKS = re.compile(r"^(thanks|thank you|thx|cheers|nice|great|awesome|perfect|well done)\b", re.IGNORECASE)


def answer_question(text: str) -> str:
    lowered = text.lower().strip(" ?!.")

    if _GREETINGS.match(lowered):
        return "Hello. Systems are online and ready. What would you like to do?"

    if _THANKS.match(lowered):
        return "Any time. What is next?"

    if re.search(r"\b(who are you|what are you|your name)\b", lowered):
        return ("I am JARVIS, a desktop assistant running locally on your Windows machine. I can open apps and "
                "folders, create and edit documents, search the web, run read-only diagnostics, and answer questions.")

    if re.search(r"\b(how are you|how do you do)\b", lowered):
        return "All systems nominal. What can I do for you?"

    if re.search(r"\b(weather|temperature outside|forecast)\b", lowered):
        return ("I cannot read live weather without an internet API key. Ask me and I will open a forecast page "
                "for your city - try: \"search weather in <your city>\".")

    if re.search(r"\b(what can you do|your capabilities|help me)\b", lowered):
        return _HELP

    topic = re.sub(r"^(what(?:'s| is)|whats|explain|define|describe|tell me about|teach me|help me (?:with|understand|study))\s+", "", lowered)
    topic = re.sub(r"^(a|an|the)\s+", "", topic).strip(" ?!.")
    topic = re.sub(r"\s+in (dbms|python|java|c\+\+|javascript|sql)$", "", topic)

    if topic in _KNOWLEDGE:
        return _KNOWLEDGE[topic]

    for key, value in _KNOWLEDGE.items():
        if key in topic or topic in key:
            return value

    words = {w for w in re.findall(r"[a-z]{3,}", topic)}
    best: tuple[int, str] | None = None
    for key, value in _KNOWLEDGE.items():
        overlap = len(words & set(key.split()))
        if overlap and (best is None or overlap > best[0]):
            best = (overlap, value)
    if best:
        return best[1]

    if re.search(r"^(write|give me|show me|create)\b", lowered):
        return ("Tell me the file to put it in and I will write it - for example: "
                "\"write a python program for binary search into bsearch.py\".")

    return (
        f'I do not have a local answer for "{topic}" yet. My offline knowledge base covers common computer-science '
        f"topics such as python, recursion, dbms, sql, data structures, big-O, networking and machine learning. "
        f"For anything else, add a valid API key (JARVIS_API_KEY or OPENAI_API_KEY) and restart me - then I answer "
        f"every question with a full language model."
    )


_HELP = (
    "Here is what I can do.\n\n"
    "**Desktop** - \"open chrome\", \"open vs code\", \"open file explorer\", \"open my downloads folder\"\n"
    "**Web** - \"open youtube\", \"google quantum computing\", \"search youtube for python tutorials\"\n"
    "**Documents** - \"create a file called notes.txt\", \"create a python file called test.py\", "
    "\"create a folder called Projects\", \"write a study plan into studyplan.txt\", \"read notes.txt\", "
    "\"add today's notes to it\"\n"
    "**Files** - \"list files in documents\", \"delete study.txt\" (I will ask first), \"rename notes.txt to todo.txt\"\n"
    "**System** - \"system status\", \"what time is it\", \"disk space\", \"run ipconfig\", \"lock my computer\"\n"
    "**Questions** - \"explain recursion\", \"what is a binary tree\", \"write a python program for binary search\"\n\n"
    "Dangerous actions always ask for your confirmation before I do anything."
)
