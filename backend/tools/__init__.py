"""Desktop tool layer: applications, files, web and system operations."""

from . import apps, files, registry, safety, system, web  # noqa: F401

__all__ = ["apps", "files", "registry", "safety", "system", "web"]
