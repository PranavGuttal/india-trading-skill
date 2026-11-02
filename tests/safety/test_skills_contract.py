"""The skills, agents and plugin files are the product Claude loads: check
they are well-formed and that every command they tell Claude to run exists
with those exact options."""
import json
import re
import shlex
from pathlib import Path

import pytest
import yaml

from india_trading.cli import build_parser

ROOT = Path(__file__).resolve().parents[2]
SKILLS = sorted((ROOT / "skills").glob("*/SKILL.md"))
AGENTS = sorted((ROOT / "agents").glob("*.md"))
PREFIX = 'python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py"'


def front(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path}: frontmatter must start on line 1"
    _, fm, body = text.split("---\n", 2)
    return yaml.safe_load(fm), body


def test_there_are_many_skills_and_agents():
    assert len(SKILLS) >= 26 and len(AGENTS) >= 5


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_skill_frontmatter(path):
    fm, body = front(path)
    assert fm["name"] == path.parent.name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", fm["name"])
    d = fm["description"]
    assert 80 <= len(d) <= 1024, f"description length {len(d)}"
    assert "Use when" in d or "Use only when" in d or "Use for" in d
    assert len(body.splitlines()) < 500
    assert "python -m india_trading.cli" not in body             # plugin launcher only


def _commands(text: str) -> list[str]:
    """Commands in fenced code blocks (one per line) and in inline `code` spans."""
    out, fenced = [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if fenced and line.strip().startswith(PREFIX):
            out.append(line.strip()[len(PREFIX):].split("#")[0].strip())
    for span in re.findall(r"`([^`]+)`", re.sub(r"```.*?```", "", text, flags=re.S)):
        if span.startswith(PREFIX):
            out.append(span[len(PREFIX):].strip())
    return [c for c in out if c]


ALL = [(p.parent.name if p.name == "SKILL.md" else p.stem, c) for p in SKILLS + AGENTS for c in _commands(p.read_text(encoding="utf-8"))]


@pytest.mark.parametrize("where,cmd", ALL, ids=[f"{w}: {c[:40]}" for w, c in ALL])
def test_every_documented_command_parses(where, cmd):
    if cmd in ("--setup", "--guard"):
        return                                                     # launcher flags, not CLI commands
    argv = shlex.split(cmd.replace("...", ""))
    try:
        build_parser().parse_args(argv)
    except SystemExit as e:
        pytest.fail(f"{where}: `{cmd}` does not parse ({e})")


@pytest.mark.parametrize("path", AGENTS, ids=lambda p: p.stem)
def test_agents_are_read_only(path):
    fm, body = front(path)
    assert fm["name"] == path.stem and fm.get("description")
    tools = {t.strip() for t in str(fm.get("tools", "")).split(",")}
    assert not tools & {"Write", "Edit", "NotebookEdit"}, f"{path.stem} must not edit files"


def test_plugin_manifest_marketplace_and_hook():
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", plugin["name"])
    pyver = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    assert plugin["version"] == pyver
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert market["plugins"][0]["name"] == plugin["name"]
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    h = hooks["hooks"]["PreToolUse"][0]
    assert re.search(h["matcher"], "mcp__groww__place_order") and re.search(h["matcher"], "mcp__claude_ai_Groww__get_quote")
    assert not re.search(h["matcher"], "Bash")
    assert "${CLAUDE_PLUGIN_ROOT}" in h["hooks"][0]["command"]
    assert (ROOT / "scripts" / "guard.sh").exists() and (ROOT / "scripts" / "india.py").exists()


def test_navigator_lists_every_skill():
    nav = (ROOT / "skills" / "india-trading-navigator" / "SKILL.md").read_text(encoding="utf-8")
    missing = [p.parent.name for p in SKILLS if p.parent.name != "india-trading-navigator" and p.parent.name not in nav]
    assert not missing, f"navigator does not mention: {missing}"
