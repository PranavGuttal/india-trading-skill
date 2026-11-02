"""Where files live when the toolkit runs inside any project folder.

Project files (settings, data, state, your own config) are relative to the
current folder: the project Claude Code is working in. Reference files that
ship with the plugin (holiday list, sector map, Groww tool classification)
are read from the project's config/ first and fall back to the copies
bundled with the plugin, so a fresh project works without copying them.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[2]


def config_file(name: str) -> Path:
    """config/<name> in the project if present, else the plugin's bundled copy."""
    local = Path("config") / name
    if local.exists():
        return local
    bundled = PLUGIN_ROOT / "config" / name
    return bundled if bundled.exists() else local
