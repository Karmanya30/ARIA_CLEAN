# Local account setup — 17 October 2026

Email/password login is enabled on the operator's localhost installation. The operator explicitly selected the most recently active private profile, which has three saved research reports. An offline provisioning operation created an account using that profile's existing owner ID; it did not combine older owners or rewrite existing financial/profile/report/chat records.

The local configuration now sets `ARIA_AUTH_MODE=accounts`, `ARIA_APP_ORIGIN=http://localhost:5173`, and `ARIA_AUTH_ALLOW_SIGNUP=1`. Other environment values were preserved. The database and previous environment file were backed up in the ignored `.audit/local-demo-migration/` directory. The dummy credentials are stored only there and provided directly to the operator; they are not included in tracked source or reports.

Before provisioning, there were no account records. The selected owner has one financial profile, three saved reports, one conversation-style record, one archived conversation and one owned audio artifact; it has no transaction rows. Twelve original non-auth tables were hashed before and after provisioning and matched exactly. Creating a dummy login does not make the existing profile's contents synthetic; they remain the operator's pre-existing data and should not be shared as a public demo dataset.

`python -m scripts.provision_local_account` is an offline administrator tool for an existing local SQLite owner. It backs up committed SQLite/WAL contents, validates the account credentials and owner, refuses existing account/email collisions, hashes the password with the existing authentication implementation, and inserts the account in a transaction. It is deliberately not a web endpoint for claiming arbitrary private IDs.

When an offline administrator provisions the same private owner as an account, the shared sign-in gate preserves that browser's current chat selection during its first private-to-account transition. Other account changes still reset the selected session, and server-side conversation ownership remains enforced.

Real localhost Chromium verification exercised the actual login and session API, matched the profile's income/age against SQLite without changing them, retrieved all three reports, verified chat selection, refreshed successfully, signed out, and confirmed protected reads return 401. A separate isolated account suite continues to cover cross-account access and session revocation. Google sign-in is available only if a real client ID is configured; no Google consent was fabricated or newly configured here.

Account mode retains its documented restrictions on unscoped paid-video/forecast/scenario controls. Email verification, account recovery and MFA remain outside the current implementation. This is a local demonstration configuration, not a claim of completed production hardening.

Final validation: 1,158 Python tests passed and 32 browser workflows passed (28 private, four account), including a complete rerun after correcting the obsolete Explore selector and isolating private test auth mode. Build, lint, both restart checks, native memory, dependency compatibility, advisory checks and live intent passed. The external connections check retains the FRED timeout. Lint has 73 warnings; Python has 104 warnings.
