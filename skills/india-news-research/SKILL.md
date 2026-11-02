---
name: india-news-research
description: >-
  Research news, SEBI/exchange circulars, quarterly results, FII/DII flows
  and macro scenarios for NSE stocks and sectors with sourced, dated
  findings, using the read-only india-news-analyst, india-results-analyst,
  india-flows-analyst and india-scenario-analyst agents. Use when the user
  asks "any news on X", "why did X fall/jump", "X results", "SEBI circular",
  "are FIIs selling", "what does this RBI/budget news mean for my stocks",
  or before trading a stock that gapped on volume.
---

# india-news-research

Delegate to the agent that fits and relay its findings with their sources:

| Question | Agent |
|---|---|
| Recent news / why a stock moved / SEBI & exchange circulars | `india-news-analyst` |
| Quarterly results, fundamentals, what changed vs last year | `india-results-analyst` |
| A headline's effect on sectors and holdings ("agar ye hua toh") | `india-scenario-analyst` |
| FII/DII buying or selling, bulk/block deals | `india-flows-analyst` |

Give the agent the symbol(s), the date range, and any price facts from
`technical` or `screen` (e.g. "gap up 6% on 3× volume on 2026-10-29").

## Rules

- Every fact needs a source and a date; unsourced claims are left out.
  Prefer primary sources: NSE/BSE filings, company releases, RBI/SEBI.
- Separate what happened (facts) from interpretation.
- News explains the past; it does not make a trade safe. A news-driven gap
  is still a gap risk for stops.
- Never fabricate results numbers; if a figure is not found, say so.
- Not advice.
