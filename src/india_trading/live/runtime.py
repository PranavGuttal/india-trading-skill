"""Can Claude safely SEND a live order from where this command is running?

The guard hook is the code-level gate on Groww order tools, and hooks only run
in Claude Code. In the Claude desktop/web app, skills run in a temporary cloud
sandbox (no state, no hook), so a "send via Claude" approval there would have
no gate at all. This module checks, without trusting anything the model says:

  1. this process was started by Claude Code (Claude Code sets CLAUDECODE=1
     in the environment of the commands it runs), and
  2. a PreToolUse guard hook covering MCP tools is configured, either in the
     project (.claude/settings.json) or by the installed plugin (the code runs
     from ~/.claude/plugins/... or CLAUDE_PLUGIN_ROOT is set, and its
     hooks/hooks.json covers MCP tools).

If either check fails, `live approve --send-via claude` is refused. The
user can still approve with `--send-via app` and place the order themselves.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

from ..paths import PLUGIN_ROOT

PROBE = "mcp__any_server__place_order"


@dataclass
class RuntimeCheck:
    ok: bool
    problems: list[str] = field(default_factory=list)
    hook_source: str = ""


def _hook_covers_mcp(cfg: dict) -> bool:
    for entry in (cfg.get("hooks") or {}).get("PreToolUse") or []:
        matcher = entry.get("matcher") or ""
        cmds = " ".join(str(h.get("command", "")) for h in entry.get("hooks") or [])
        try:
            covers = bool(re.search(matcher, PROBE)) and bool(re.search(matcher, "mcp__claude_ai_Groww__x"))
        except re.error:
            covers = False
        if covers and ("guard" in cmds):
            return True
    return False


def _load(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, ValueError):
        return None


def check(env: Optional[Mapping[str, str]] = None, project_dir: Optional[Path] = None) -> RuntimeCheck:
    env = os.environ if env is None else env
    problems: list[str] = []
    if env.get("CLAUDECODE") != "1":
        problems.append("not running inside Claude Code (CLAUDECODE=1 not set). The guard hook only works in "
                        "Claude Code; in the Claude app use --send-via app and place the order yourself.")
    source = ""
    project = Path(project_dir or env.get("CLAUDE_PROJECT_DIR") or Path.cwd())
    for cand in (project / ".claude" / "settings.json", project / ".claude" / "settings.local.json"):
        cfg = _load(cand)
        if cfg and _hook_covers_mcp(cfg):
            source = str(cand)
            break
    # Installed as a Claude Code plugin: the code runs from ~/.claude/plugins/..., whose hooks.json is active.
    plugin_root = Path(env["CLAUDE_PLUGIN_ROOT"]) if env.get("CLAUDE_PLUGIN_ROOT") else (
        PLUGIN_ROOT if {".claude", "plugins"} <= set(PLUGIN_ROOT.parts) else None)
    if not source and plugin_root is not None:
        cfg = _load(plugin_root / "hooks" / "hooks.json")
        if cfg and _hook_covers_mcp(cfg):
            source = f"plugin {plugin_root / 'hooks' / 'hooks.json'}"
    if not source:
        problems.append("no guard hook covering MCP tools found in .claude/settings.json or the installed plugin")
    return RuntimeCheck(ok=not problems, problems=problems, hook_source=source)
