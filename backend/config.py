"""
Central configuration for JARVIS.

Nothing here is hardcoded with secrets.  The LLM key and endpoint are read from
environment variables so the same code runs for OpenAI, a compatible gateway,
or a local model server (Ollama / LM Studio / llama.cpp) exposed over an
OpenAI-compatible HTTP API.
"""

from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

MEMORY_FILE = DATA_DIR / "memory.json"

# --------------------------------------------------------------------------- #
# Server
# --------------------------------------------------------------------------- #
HOST = os.environ.get("JARVIS_HOST", "127.0.0.1")
PORT = int(os.environ.get("JARVIS_PORT", "8765"))


# --------------------------------------------------------------------------- #
# LLM
# --------------------------------------------------------------------------- #
def _first_env(*names: str) -> str:
    """Return the first non-empty environment variable from *names*."""
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return ""


# Note: "OPENAAI_API_KEY" (with the double A) is honoured on purpose - that is
# the variable that already exists in this environment. "OPENAI_API_KEY" and
# JARVIS_API_KEY take precedence if they are set later.
LLM_API_KEY = _first_env("JARVIS_API_KEY", "OPENAI_API_KEY", "OPENAAI_API_KEY")
LLM_BASE_URL = (_first_env("JARVIS_BASE_URL", "OPENAI_BASE_URL") or "https://integrate.api.nvidia.com/v1").rstrip("/")
# Default: nemotron-3-super-120b-a12b is the best model on NVIDIA's API for
# function calling - tested at ~1s response time with correct tool usage.
LLM_MODEL = _first_env("JARVIS_MODEL", "OPENAI_MODEL") or "nvidia/nemotron-3-super-120b-a12b"
LLM_TIMEOUT = float(os.environ.get("JARVIS_LLM_TIMEOUT", "30"))
LLM_ENABLED = os.environ.get("JARVIS_DISABLE_LLM", "").lower() not in ("1", "true", "yes")
LLM_MAX_HISTORY = int(os.environ.get("JARVIS_HISTORY", "12"))

ASSISTANT_NAME = "JARVIS"


# --------------------------------------------------------------------------- #
# User locations / workspace
# --------------------------------------------------------------------------- #
HOME = Path(os.path.expanduser("~")).resolve()
DESKTOP = HOME / "Desktop"
DOCUMENTS = HOME / "Documents"
DOWNLOADS = HOME / "Downloads"

# Relative paths with no anchor are created inside this folder so the user
# always knows where the assistant put things.
WORKSPACE = Path(os.environ.get("JARVIS_WORKSPACE", str(DESKTOP / "JARVIS"))).resolve()

TEMP = Path(os.environ.get("TEMP") or os.environ.get("TMP") or str(HOME)).resolve()


def ensure_workspace() -> Path:
    """Create the workspace folder on first use and return it."""
    try:
        WORKSPACE.mkdir(parents=True, exist_ok=True)
    except OSError:
        return HOME
    return WORKSPACE
