# Third-party notices

## FinRobot (AI4Finance Foundation) — Apache License 2.0

The equity-research intelligence layer (`modules/equity_research/intelligence/`) adapts
design concepts and calibration ideas from **FinRobot**
(<https://github.com/AI4Finance-Foundation/FinRobot>, Copyright © 2024-2026 AI4Finance
Foundation, licensed under the Apache License, Version 2.0).

The code in this repository is an independent implementation in ARIA's own architecture;
no FinRobot source files were copied. The following ideas are adapted from FinRobot V2
(`finrobot_desktop/`):

| Adapted idea | Where in ARIA |
|---|---|
| "Numbers are computed by code, narratives are LLM-assisted, every output is provenance-tracked" | `facts.py`, `agents.py` |
| DCF structure and guard rails (terminal growth below WACC, minimum WACC-growth spread, non-positive terminal cash flow, negative equity → refuse), steady-state terminal reinvestment, sensitivity grid, ±2pp margin swing, reverse DCF | `valuation.py` |
| Asymmetric Blume beta adjustment | `valuation.py` |
| DDM with terminal-payout normalisation | `valuation.py` |
| Peer multiples: sanity bounds vs "not meaningful" caps, median with the company kept in the set | `comps.py` |
| Multi-method synthesis: method-agreement confidence tiers, tier-widening verdict bands, "withhold the number, never the judgment" | `comps.py` |
| Audit findings with `info` / `review` / `blocked` severities and a report-level status | `audit.py` |
| Bull / bear / judge roles that cite evidence ids rather than write numbers | `agents.py` |

Thresholds were re-tuned for Indian large caps. The Apache-2.0 license text is at
<https://www.apache.org/licenses/LICENSE-2.0>. "FinRobot" and "AI4Finance" are trademarks of
the AI4Finance Foundation; this project is not affiliated with or endorsed by them, and does
not use the name as a product or feature name.

## virattt/ai-hedge-fund — MIT License

The scenario and fundamental-analysis sections of the intelligence layer
(`modules/equity_research/intelligence/`) use two ideas from **ai-hedge-fund**
(<https://github.com/virattt/ai-hedge-fund>, MIT License): a probability-weighted
bear/base/bull value, and the residual income model concept. ARIA's implementation is
independent; no source code was copied.

## Academic methods

Published methods implemented independently in `modules/equity_research/intelligence/`:

- Piotroski (2000) F-score
- Sloan (1996) accruals
- Damodaran's fundamental growth (reinvestment rate x return on capital)
- Buffett's owner earnings (1986 Berkshire Hathaway letter)
- Edwards-Bell-Ohlson residual income model

## Data sources and text used at run time

| Source | Used for | Terms note |
|---|---|---|
| screener.in (public pages) | Financial statements, quarterly shareholding pattern, flagged promoter pledge | Check screener.in's terms of use for your deployment. |
| Yahoo Finance via `yfinance` | Quotes, profile, management, balance-sheet detail (Altman Z), peer multiples, analyst targets, index history | Personal/educational use per Yahoo's terms; data may be delayed. |
| Google News RSS | Recent headlines (titles only, shown with publisher and date) | Headlines are attributed to their publishers. |
| Wikipedia (REST summary API) | Company and industry background text | Text is licensed CC BY-SA 4.0; reports show the article title, a link and the licence. |
| mfapi.in (AMFI NAV data) | Mutual-fund NAV history, including the index fund used as the total-return benchmark proxy | Public NAV data; verify against the AMC factsheet. |
| AMFI daily NAV file (portal.amfiindia.com) | Active scheme list and categories (scheme lookup, category ranks) | Public data published by AMFI. |

Reports state each source and its data-through date on their disclosure page.
