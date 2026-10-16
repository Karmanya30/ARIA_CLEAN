# Startup recovery — 2026-10-17

The user's existing `localhost:5173` page showed an ARIA error card saying **Not Found**. Direct requests reproduced HTTP 200 from `/api/health` but HTTP 404 from `/api/auth/session`, both through the Vite proxy and directly on the API. The running backend was an older process started before account endpoints were added. The launcher accepted its unchanged health response and reused it after the code update.

## Repair

- `api/runtime_version.py` hashes backend Python source paths/content and dependency declarations without loading `.env`, importing application configuration, or opening a database. Frontend files, tests, caches and credentials are excluded. The API snapshots that revision when imported and returns it from its public health check.
- The launcher compares the live revision with current workspace source, then verifies that the session endpoint returns a supported mode. A healthy but outdated backend is restarted only after its process command and ARIA API identity match this workspace. An unrecognized/different workspace process is left running with an error. The frontend proxy must also reach the current session service before the launcher reports readiness. A valid current process is reused.
- The frontend gives specific launcher/retry instructions for the missing session endpoint, handles unreadable responses and connection failures, and limits auth requests to 15 seconds. A missing session service never silently enables private/guest access.

## Operational recovery on the user's local application

A consistent SQLite backup was created with SQLite's online backup API under ignored `.audit/runtime-recovery/` before the targeted restart. No row values or credential values were printed. The launcher then restarted the verified `E:\ARIA` API on port 8000, loading the additive tables/columns already implemented by the preceding work. This was a **real local backend restart**, separate from the isolated regression servers. `.env` was not changed.

After recovery, all ten pre-existing tables were compared locally against the backup using hashes of their pre-restart columns. Existing row content matched across all ten; no data values were printed. New additive schema objects were not mistaken for changes to existing facts.

The existing Vite server on 5173 was retained. A second launcher invocation kept the same new API process, proving unchanged source does not cause a restart loop. No new Edge window or paid video session was opened.

Real Chromium against `http://localhost:5173/#/chat` confirmed session HTTP 200, the chat composer visible, and no page errors. The session, frontend and proxy requests were real. Chat history was intercepted with an empty fixture solely to avoid creating a synthetic conversation in the user's real DB; no chat message was submitted. Screenshot and machine-readable results are retained under `.audit/runtime-recovery/`. The original browser tab can recover by clicking **Retry connection** or refreshing.

## Regression scope

Four new Python regressions cover revision changes from source/config/dependency/path edits, ignored frontend/cache changes, the loaded health snapshot/session route, and actual PowerShell readiness/ownership functions extracted without executing the launcher body. The latter rejects old health-only APIs, absent/invalid session services and another workspace's process.

Two new Chromium scenarios (one per UI version) reproduce the exact session 404, assert the recovery instructions, verify the application remains closed, restore the real isolated session endpoint and open the profile via the Retry button. Both private/account workflows and the complete final system audit are rerun; authoritative totals are in `SYSTEM_AUDIT_RESULTS.json` and `.audit/rerun/summary.json`.

Final result: **1,143 Python tests and all 22 Chromium workflows passed**, with zero failures/errors/skips; both restart checks, build/types, lint, native memory and dependency/security checks passed. Existing warnings remain (104 Python, 73 lint), and Python/npm scans reported zero known advisories. The overall runner correctly returned 1 solely because the public FRED connection still timed out.

FRED connectivity, live Google consent, physical voice/video and previously documented deployment/financial limitations are separate from this startup repair. Source revision checks do not detect environment-only changes or replace a production process supervisor. An intentional environment change still requires an API restart.
