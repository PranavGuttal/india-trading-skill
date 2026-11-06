---
name: india-setup
description: >-
  Install and health-check the India trading toolkit in the current project:
  create the plugin's Python environment, check packages, settings, real
  data, indices, holiday list, Groww tool classification and the guard hook,
  and say exactly what to do next. Use when the user says "set it up",
  "install", "it doesn't work", "doctor", "check my setup", or a command
  fails with missing packages.
---

# india-setup

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" --setup
python "${CLAUDE_PLUGIN_ROOT}/scripts/india.py" doctor
```

Use `python3` if `python` is not found. `--setup` creates
`${CLAUDE_PLUGIN_ROOT}/.venv` and installs pandas, numpy, pydantic, PyYAML
and tzdata there; later commands find it on their own. Ask before running it
(it downloads packages).

## After `doctor`, fix each ✗ in this order

1. **Settings** — optional. Copy `${CLAUDE_PLUGIN_ROOT}/config/settings.example.yaml`
   to `config/settings.yaml` in the project only if the user wants to change
   limits. Without it, safe defaults apply (paper, ₹200 budget, 90% floor).
   To invest more or less, use `budget set N`; the limits scale with it.
2. **Data** — `data-fetch --universe large_caps_20 --indices --etf` (internet;
   see india-data-manager). Then set `data_dir: data/real` and the watchlist.
3. **Holidays** — ask the user to open nseindia.com → Resources → Exchange
   communication → Holidays in their browser and paste the equity list for
   the year; write it to `config/nse_holidays.yaml`. Never add dates from memory.
4. **Groww tools** — only when the Groww connector is connected: list its
   tools, read schemas, fill `config/groww_tools.yaml` with the user.
5. **Guard hook** — shipped in the plugin (`hooks/hooks.json`). After
   installing or updating the plugin, the user restarts Claude Code (or opens
   `/hooks`) so it loads.

Report what passed and what is still missing. Never ask for passwords, PINs,
OTPs or API keys; the Groww connector handles its own login.
