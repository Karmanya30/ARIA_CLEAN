# Optional account authentication — 2026-10-17

Email/password and Google sign-in are implemented behind `ARIA_AUTH_MODE=accounts`. The default remains `private`, as requested. `.env` has not been changed; existing private-mode profiles, UUIDs and conversations are not automatically assigned to an account.

## Enable and configure

For the current local single-user application, keep `ARIA_AUTH_MODE=private`. `python -m api.main` now binds `127.0.0.1` by default, matching the existing launcher; `ARIA_BIND_HOST` permits an intentional override. Private mode has no account boundary and is not an internet deployment configuration.

To enable accounts, set the following in your local environment and restart the API:

```dotenv
ARIA_AUTH_MODE=accounts
ARIA_APP_ORIGIN=http://localhost:5173
ARIA_AUTH_ALLOW_SIGNUP=1
GOOGLE_CLIENT_ID=your-web-client-id.apps.googleusercontent.com
```

The origin must exactly match the browser address. Configure that authorized JavaScript origin on a Google OAuth **Web application** client. No Google client secret is required for this ID-token flow. A blank client ID hides Google sign-in; email/password remains available. Use HTTPS outside loopback; the configuration rejects non-local HTTP origins. Signup defaults to disabled and can be disabled again after provisioning intended accounts. Invalid mode names fail startup rather than opening private access.

Both UI versions share the same sign-in screen and account menu. Register a password account, then explicitly connect the matching Google identity from the account menu to use either method for that account. Google-only signup is also supported. Merely matching an email address never silently links identities: Google email ownership has nuances, and an attacker-controlled local signup must not become someone else's linked account. The linking operation requires the existing authenticated session and matching Google email.

Implementation follows Google's [backend ID-token verification guide](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token) and [JavaScript sign-in reference](https://developers.google.com/identity/gsi/web/reference/js-reference). The official `google-auth` verifier checks the RSA signature, audience, issuer and token times; ARIA additionally enforces configured audience/issuer, verified email and a browser-cookie-bound nonce. Certificate requests have a ten-second timeout. Invalid credentials produce a private generic error. Browser challenges expire after ten minutes and are reused across status reads/tabs while valid; refreshing the page obtains a new challenge after expiration.

## Session and ownership boundary

New additive SQLite tables are `auth_accounts`, `auth_sessions` and `auth_throttles`. `audio_artifacts` gains a nullable `owner_id` through the existing additive migration helper. No existing private records are claimed or deleted. Back up the database before enabling accounts; rollback to private mode preserves account records but removes account protection, so it must remain local. Disabling account mode is not a safe public-server rollback.

- Passwords use PBKDF2-HMAC-SHA256 with 600,000 iterations and a random 128-bit salt. Passwords are bounded to 12–128 characters and never returned.
- Session cookies contain 256-bit random tokens. Only SHA-256 token digests are stored in SQLite, with seven-day expiry. Cookie flags are HttpOnly, SameSite=Strict, path `/`, and Secure for HTTPS. Login creates a fresh token; at most ten sessions per account are retained. Expired sessions are pruned on later login.
- All HTTP application routes require a valid session in account mode except health and the explicitly public auth endpoints. Mutations, including login/logout, require the exact configured Origin. Owner IDs in query, JSON and multipart must match the account. Missing owner IDs are rejected on routes whose fallback would otherwise select a different owner. Duplicate owner query parameters cannot bypass checks.
- Profiles, transactions/import previews and reports are account-owned. Conversation ownership is checked by the existing durable archive; progress/quiz endpoints also check conversation ownership. Account learning records use a separate account-and-session key, so selecting an old private session ID cannot claim its legacy learning state. Completed audio is bound to its owner, including the avatar-render lookup. Legacy unowned audio is inaccessible in account mode.
- Live WebSockets check the cookie and Origin at connection, then re-check revocation/expiry and owner on incoming messages. Cross-account conversations are rejected before provider work.
- Logout revokes the current server session; “Sign out all devices” revokes all account sessions. Copied old cookies fail even after API restart. Other open tabs receive a storage event, reload session state and unmount the old user's application. Account changes reset active conversation selection and remount application state; the legacy private owner key is preserved.
- Sign-in failures have a persistent ten-attempt/15-minute email-key budget, bounded to 4,096 live throttle entries, in addition to the per-worker socket-peer POST limits. Successful password sign-in clears its email throttle. These limits do not replace deployment-wide abuse controls.

Account mode deliberately blocks Tavus/custom-LLM callbacks and forecast/scenario job routes, and report generation skips its automatic forecast/scenario queue submissions. Those integrations currently have global mutable state and shared cancellation/control; their account isolation has not been implemented. They remain available in private mode. This avoids introducing account login around still-unscoped controls and advertising complete tenant isolation.

## Verification and limits

The Python account suite exercises actual SQLite account/session hashes, a fresh interpreter, cookie rotation/expiry/revocation, CSRF, registration controls, cross-account profile/transaction/report/chat/progress/audio access, multipart import ownership, and WebSocket revocation. Google tests use locally generated RSA keys and a test certificate transport with the **real Google verifier**, checking bad signature/audience/issuer/expiry/nonce and unverified email, plus explicit linking and nonce stability.

Four Chromium scenarios exercise email signup/login in v1 and v2, profile saves confirmed directly in SQLite, navigation/refresh, sign-out in multiple tabs, a fresh browser login, another account's empty profile and denied cross-account read. An authenticated chat additionally creates a real fixture report, renders its HTML in the browser iframe and downloads JSON. Google browser flows use a **test-only local identity/script adapter**, cover Google signup/refresh and explicit linking followed by Google login, and never contact a real Google account. The adapter exists only in `scripts.audit_server`, not the production application.

`scripts.audit_account_restart` starts three real isolated API processes. It verifies the login cookie and saved profile survive restart, then that a copied revoked cookie is rejected after another restart. The one-command system audit now includes both account browser and account restart checks in addition to private-mode coverage.

Live Google OAuth consent is **NOT VERIFIED**: it needs a real configured client ID, authorized origin and user sign-in. This implementation does not include email delivery/verification, forgotten-password recovery, MFA, administrator roles, account deletion, or a private-data migration wizard. Email is a login identifier, not a claim that local signup verified mailbox ownership. Physical voice/video and full public-deployment hardening remain outside the result. Browser storage unavailability can prevent cross-tab notifications, but the server still enforces sessions and owners. Already downloaded files cannot be revoked.

The account implementation checkpoint passed 1,139 Python tests, all 16 private-mode browser scenarios and all four account browser scenarios, plus both actual restart checks. There were no test failures/errors/skips; the one-command runner exited 1 for FRED's external timeout. Google consent with a real user was not silently counted as passing. Subsequent [startup recovery](STARTUP_RECOVERY.md) and current totals are recorded in `SYSTEM_AUDIT_RESULTS.json`.
