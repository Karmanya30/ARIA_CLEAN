# Statement-import continuation

The previous audit identified process-local previews, import races and separate profile/transaction commits (R04). This continuation fixes the statement portion of that gap. Audio-token durability and production authentication remain separate open items.

## Changes

- Normalized previews and retry results now live in the existing SQLite database, in the additive `statement_previews` table. Source files are never saved.
- Imports acquire SQLite's writer lock **before** reading/deduplicating. Separate threads, API workers and overlapping preview IDs cannot both import the same matching rows.
- Transactions, optional profile changes and the completed retry result commit in one transaction. Profile validation/storage failure rolls everything back and leaves the preview retryable.
- Retrying the same `(owner, import_id, apply_to_profile)` operation returns its original result without writing again. Changing `apply_to_profile` from false to true is a separate explicit operation; it can apply averages after a transaction-only import.
- A repeated completed import cannot overwrite a later profile edit. When confirmed averages replace an expense breakdown, omitted old categories are explicitly removed instead of silently merged back.
- Preview access and retry results expire after ten minutes. Expired rows are pruned on later parse/import activity; this is not a timer or a guarantee of forensic erasure from database backups/free pages. Deleting finance data or clearing transactions invalidates that owner's pending previews and receipts.
- Upload text explains the temporary preview. Imported transactions remain until the user clears them, as before.

Identical request retries now return the original imported count. A different upload of the same rows still reports duplicate counts. After expiry or explicit deletion, the old import ID returns 404 and cannot resurrect cleared transactions.

## Spreadsheet safety and numeric validation

Before opening XLSX/XLSM workbooks, the parser checks ZIP metadata: at most 2,000 members and 50 MiB total expanded size. Workbooks are limited to 32 sheets, 128 columns, 21,000 source rows per sheet (20,000 transaction limit plus headers), and one million grid cells across sheets. Workbooks close even when a limit fails. Limits return a readable 413 with a CSV/shorter-period suggestion.

Nonfinite, out-of-range, and amounts that round to zero paise are rejected before a normalized preview is stored. This closes the uploaded-number path that could bypass the manual-transaction API schema.

These limits are not comprehensive upload sandboxing. Legacy XLS, PDF extraction, global request/compute admission, rate limits and multi-user deployment security still need review. A bounded workbook is not proof that an untrusted parser can never exhaust CPU or memory.

## Schema and compatibility

The new table is created through existing `Base.metadata.create_all` when the updated application starts. Existing profile and transaction rows are not rewritten. Profile saving supports an internal shared SQLAlchemy session; ordinary callers keep the previous independent commit behavior.

The import transaction implementation targets the project's SQLite backend. It is not advertised as portable PostgreSQL/multi-database locking. No database credentials or `.env` settings changed. Test processes use isolated databases.

For source rollback, the continuation's original files are in `.audit/before-import-remediation.zip`; the existing overall audit backup is also retained. Reverting source can leave the new table in place. Do not automatically drop it: doing so discards pending previews and retry records.

## Verification

- Focused parser/profile/import regressions: 47 passed.
- Real Chromium import/retry/refresh workflows: passed in both v1 and v2.
- Concurrent requests: tested with both shared and separate preview IDs, including two separate Python processes against the same SQLite file.
- Failure injection after the profile write: verified no transaction rows, profile changes or success receipt survived; a subsequent retry succeeded.
- Three actual API process lifetimes: parse before restart, import after restart, retry after another restart; no duplicate transactions and no overwrite of a later profile edit. Direct SQLite count was checked.
- Invalid numeric uploads and compressed/sparse workbook bounds have regression tests.

Final whole-application rerun: **1,094 Python tests passed, zero failures/errors/skips; all 16 Chromium workflows passed**. Build/types, lint, restart, native memory, dependency consistency and both security scans passed. Lint still reports 73 warnings. The runner returned a failure only for the FRED connection timeout; other configured live probes and the intent evaluation completed.

The final full regression/browser/build/security rerun is recorded in `.audit/rerun/summary.json` and summarized in `SYSTEM_AUDIT_RESULTS.json`; focused passes alone are not the final acceptance criterion.

Pending preview UI state is not restored after a browser refresh or closing the page; re-uploading is safe because persisted rows are deduplicated. The verified preview restart case keeps the import ID while the API process restarts. This should not be described as full draft-session recovery.
