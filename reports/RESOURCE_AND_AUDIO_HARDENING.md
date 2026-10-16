# Resource and completed-audio hardening — 2026-10-17

Status: verified for the exercised limits and completed-audio workflows; overall application remains PARTIALLY VERIFIED.

The previous audit's unresolved resource and audio findings were investigated without resetting existing work, changing `.env`, or launching paid video/tunnel sessions. Before editing, affected source and reports were copied to `.audit/hardening-backup/`; the preceding runner artifacts are under `.audit/before-resource-final-run/`.

## Request admission

`api/resource_limits.py` runs before application multipart/JSON parsing on `/api/`, `/v1/` callbacks and `/avatar/`. Defaults are 12 MiB total HTTP body including multipart overhead, 30 seconds to receive the body, and 16 active HTTP/WebSocket requests per worker. Declared and actual body sizes are checked independently, including chunked bodies and dishonest Content-Length values. Above 1 MiB the bounded buffer spools to temporary disk and is closed after handling. Disconnect, timeout and handler failure release the admission slot. Smaller endpoint limits still apply: statements 5 MiB and transcription 10 MiB.

POST requests and live WebSocket openings are limited to 120 per minute per socket peer per worker. Untrusted forwarded headers cannot change the key. The peer map is bounded to 4,096 entries. `.env.example` documents configuration; `0` disables only the rate limit. Pytest disables the shared rate budget to keep unrelated test cases independent; dedicated raw ASGI tests explicitly enable and exercise rejection/reset.

These are local admission limits. Multiple workers multiply capacity, reverse proxies may group many users under one socket address, and an internet deployment still needs trusted proxy configuration, deployment-wide limits and account quotas. This is not an authenticated identity or a calibrated production throughput target. Long-lived WebSockets occupy admission slots. Request timeouts cover body reception, not arbitrary model or native-library execution.

## Statement parsing

- The pure parser also checks the 5 MiB input limit, protecting non-HTTP callers.
- Legacy XLS now uses xlrd on-demand sheets, checks sheet count/dimensions/cumulative cells before converting to Python grids, preserves Excel date-cell semantics, unloads sheets and always releases resources. It no longer asks pandas to materialize every sheet at once.
- PDF rejects more than 100 pages, decoded page content over 8 MiB and extracted text over 2 million characters. Both layout and fallback reading use the limits.
- CSV/TSV/text and JSON grid construction now bound columns, rows and cumulative cells; JSON checks its union of columns before building the rectangular matrix. OFX uses incremental match iteration with a source-row cap.
- Prior XLSX ZIP-expansion and grid limits remain in force.

The libraries may allocate while decoding XLS/PDF structures before their dimensions or decoded sizes can be inspected. These checks reduce known amplification and downstream work; they are **not** a process memory sandbox, hard CPU deadline, or guarantee against every malicious document. Parser subprocess isolation and operating-system limits remain open.

## Completed speech persistence and bounded queue

`audio_artifacts` is an additive SQLite table created by normal startup. Audio tokens are opaque, random capabilities. Completed clips are copied to an application-managed `audio-cache` beside the configured database. The cache is therefore isolated with the test database too. Cached filenames are derived only from validated 32-character hexadecimal tokens; client paths are never accepted.

The queue accepts at most 16 running/queued speech callables per process, with four synthesis workers. When queue/database admission fails, text replies remain available without audio. The shared database permits at most 128 artifact entries and 128 MiB of recorded completed clips, with a 10 MiB limit per clip. File copying checks actual bytes as well as initial file size. Failed entries consume the entry budget until expiry, preventing unbounded failure records.

Tokens expire after one hour. Expired managed clips and rows are pruned lazily on later registrations. Expiry blocks access immediately; this does not promise scheduled deletion, forensic erasure or backup removal. Original synthesizer output paths are never deleted by this registry; the synthesizer's source temporary-file lifecycle is unchanged. A crash during copying can leave an uncounted partial managed file until its row expires and a later registration prunes it. Thus the byte budget describes recorded completed artifacts rather than a hard filesystem quota; apply an OS disk quota for that guarantee.

Completed audio is shared across workers and survives backend restart. Pending synthesis closures remain process-local and cannot resume after a worker dies. Such tokens wait only up to the existing 90-second resolution deadline and expire; no paid/provider work is silently replayed. This partially closes R04 rather than claiming durable speech jobs. Audio GET preserves WAV versus MPEG content type based on the bytes rather than the cache filename.

## Evidence and remaining work

New tests cover oversized/chunked/dishonest bodies, malformed headers, body timeout, concurrency rejection/recovery, peer rate limits, large spooled replay, handler failure, legacy XLS cleanup/date conversion, PDF bounds, text-grid bounds, cache quotas/expiry/source safety, queue backpressure and a fresh interpreter reading a completed clip. `scripts/audit_restart.py` additionally serves the clip through three real API lifetimes after its source is removed, alongside the existing profile/chat/statement persistence checks.

The final full-run counts and connection status are in `SYSTEM_AUDIT_RESULTS.json` and `.audit/rerun/summary.json`. Physical microphone/speaker/WebRTC, in-flight speech resumption and complete parser sandboxing remain unverified. FRED was retested against the real public endpoint and still timed out at 15 seconds; the probe remains a failure. The user selected both email/password and Google sign-in while preserving the current private mode. Optional accounts were implemented subsequently; see [account configuration, isolation and verification](ACCOUNT_AUTHENTICATION.md).

Final sequential verification passed 1,139 Python tests and all 20 browser workflows (16 private plus four accounts), with no test failures/errors/skips. Both restart checks, build/types, lint, native memory and dependency/advisory checks passed. Existing warnings remain (104 Python, 73 lint); no known Python/npm advisories were reported. The runner exits 1 solely for the real FRED timeout. A missing Yahoo price bar discovered during the earlier run was fixed with explicit exclusion/provenance warnings and regression coverage, without fabricating a price or weakening the live test.
