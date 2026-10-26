# News feed article count

The Markets news dashboard previously requested at most 30 headlines. The shared collector also limited broad briefings to two stories per publisher, which excluded additional distinct articles even before the dashboard rendered them.

The dashboard now requests `fetch_news(limit=None)`. This returns every available recent, deduplicated article from feeds that answer within the existing fetch deadline, with no total article cap or per-publisher quota. Explicitly sized chat briefings retain their existing context budgets. The dashboard still shows ten articles per page; search and filters cover the entire returned collection.

The feed remains a recent-news view (72 hours), excludes duplicate and filler headlines, and depends on what publishers expose in their RSS feeds. It is not a complete historical archive.

Regression coverage includes 75 distinct stories from one publisher, preservation of all 75 stories through dashboard sentiment/tagging, and browser workflows in both UI versions that navigate to the eighth page, search for the last article, open its details, clear search, and refresh.

Live local verification after restarting the backend returned HTTP 200 with 3,070 articles. Playwright opened the final page successfully with no browser errors. This count changes as publishers update their feeds. The local SQLite database was backed up before the restart; `.env` was unchanged.

News-change checkpoint checks: 1,145 Python tests passed; all 24 browser workflows passed (20 private-mode, four account-mode). Build, lint, both restart checks, native memory, dependency consistency, advisory checks and live intent passed. Lint reports 73 existing warnings and Python reports 104 warnings. The external FRED connectivity check still times out; other tested connections passed. The first full browser launch conflicted with the focused test server; after cleanup, the complete browser suite passed.
