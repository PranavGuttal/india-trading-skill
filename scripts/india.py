#!/usr/bin/env python3
"""Launcher for the india-trading toolkit, usable from ANY project folder.

    python <plugin>/scripts/india.py <command> [options]     # e.g. doctor, regime, screen
    python <plugin>/scripts/india.py --setup                 # one-time: create the toolkit's Python environment
    python <plugin>/scripts/india.py --guard                 # PreToolUse hook entry (reads the event on stdin)

Data, settings and state are read relative to the CURRENT folder (your
project); the code is loaded from the plugin folder. The Python packages
live in a per-user environment OUTSIDE the plugin folder (Claude Code copies
plugins into a versioned cache, and a copied venv breaks):
    Windows  %LOCALAPPDATA%\\india-trading\\venv
    others   ~/.local/share/india-trading/venv
    override INDIA_TRADING_VENV=<folder>
If the current Python lacks the packages, the first environment that can
import them is used. Nothing is installed without --setup.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPS = ["pandas>=2.1", "numpy>=1.26", "pydantic>=2.5", "PyYAML>=6.0", "tzdata>=2024.1"]
CHECK = "import numpy, pandas, pydantic, yaml"
DENY = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                               "permissionDecisionReason": "live guard could not start (Python packages missing); "
                                                           "blocked. Run scripts/india.py --setup"}}


def user_venv() -> Path:
    if os.environ.get("INDIA_TRADING_VENV"):
        return Path(os.environ["INDIA_TRADING_VENV"])
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "india-trading" / "venv"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "india-trading" / "venv"


def _py(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _works(py: Path) -> bool:
    try:
        return py.exists() and subprocess.run([str(py), "-c", CHECK], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _have_deps() -> bool:
    try:
        import numpy, pandas, pydantic, yaml  # noqa: F401
        return True
    except ImportError:
        return False


def _setup() -> int:
    venv = user_venv()
    py = _py(venv)
    if not py.exists():
        print(f"creating {venv} ...")
        venv.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.call([sys.executable, "-m", "venv", str(venv)])
        if r:
            return r
    print("installing " + ", ".join(DEPS) + " ...")
    r = subprocess.call([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q", *DEPS])
    if r == 0 and _works(py):
        print(f"done. Check with: python \"{Path(__file__).resolve()}\" doctor")
        return 0
    print("setup did not finish; see the messages above", file=sys.stderr)
    return r or 1


def main(argv: list[str]) -> int:
    guard = argv[:1] == ["--guard"]
    if argv[:1] == ["--setup"]:
        return _setup()
    if not _have_deps():
        if not os.environ.get("INDIA_TRADING_RELAUNCHED"):
            here = Path(sys.executable).resolve()
            for py in (_py(user_venv()), _py(ROOT / ".venv")):
                if py.exists() and py.resolve() != here and _works(py):
                    env = dict(os.environ, INDIA_TRADING_RELAUNCHED="1")
                    return subprocess.call([str(py), str(Path(__file__).resolve()), *argv], env=env)
        if guard:                                   # fail closed: an order tool is denied, never allowed
            print(json.dumps(DENY))
            return 0
        print("The toolkit's Python packages are not installed for this Python.\n"
              f"Run once:  python \"{Path(__file__).resolve()}\" --setup", file=sys.stderr)
        return 3
    sys.path.insert(0, str(ROOT / "src"))
    if guard:
        from india_trading.live.guard import main as guard_main
        return guard_main()
    from india_trading.cli import main as cli_main
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
