# ARIA branding update — 17 October 2026

The supplied ARIA artwork is now represented by a transparent gradient emblem and a theme-aware text wordmark. The emblem keeps the triangular A, facial silhouette and financial candlesticks. Navigation uses a compact horizontal lockup; login uses a centered lockup with the tagline. Text follows the website's light and dark colors.

## Assets and integration

- Original supplied reference: `web/public/brand/aria-reference.png`.
- Adapted transparent master: `web/public/brand/aria-mark-source.png`.
- Website PNG sizes: `web/public/brand/aria-mark-{64,128,180,256,512}.png`.
- Browser and Apple icons: `web/public/favicon.png`, `web/public/favicon.svg`, `web/public/apple-touch-icon.png`.
- Shared React branding: `web/src/components/brand/BrandLogo.tsx` and `BrandLogo.css`.
- Self-contained financial report branding: `shared/branding.py` embeds the PNG as a data URI, so downloaded HTML and browser-printed PDFs do not need a running website to display it.

Applied to login/loading/error screens, navigation, the chat welcome screen and assistant messages, market insights and news Q&A, Settings/About, avatar-page browser icons, and equity/fund report covers. Both selectable UI versions and the root component copies use the shared component. Functional voice visualizations remain interactive.

The original full artwork is preserved as a reference. The website uses an adapted emblem with readable HTML text rather than shrinking the complete square artwork into narrow navigation. Historical academic comparison PDFs retain their original publication snapshot.

## Image preparation

Mode: built-in image-generation tool, reference-image edit with transparent background enabled. Standard browser canvas resizing produced the deployment sizes from the transparent result. No external image API or API key was used.

Exact edit prompt:

> Use case: background-extraction. Edit target: attached ARIA AI Finance logo. Create a production website icon asset by extracting ONLY the triangular A-shaped emblem above the word ARIA. Preserve the supplied emblem's recognizable geometry, woman's facial silhouette, right-side financial candlesticks and cyan/blue/turquoise/violet gradient. Remove the black background completely, including black negative spaces inside the emblem, leaving actual alpha transparency. Remove all lettering, the ARIA word and tagline. Center the standalone emblem in a square canvas with about 8% transparent padding. Crisp clean edges, no added objects, no background, no drop shadow, no extra glow or checkerboard. Keep the original design faithfully; this is an extraction for the website, not a redesign.

## Verification

An isolated browser preview checked two login color modes, ten desktop/mobile theme and UI-version combinations, and a standalone financial report with an embedded logo and PDF rendering. All 13 checks passed, including image decoding, navigation-brand viewport bounds and absence of browser page errors. Screenshots and detailed results are in the ignored local `.audit/branding-preview/` directory. The preview used synthetic data and a separate database.

The focused equity-report suite passed all 24 tests. The final project-wide rerun passed 1,158 Python tests, 28 private-mode browser workflows, four account browser workflows, the build, lint (with existing warnings), both restart checks, memory evaluation, dependency consistency/advisory scans and live intent checks. The connection check failed because FRED timed out; the other six connectivity probes passed. The overall runner therefore returned exit code 1. Exact results are recorded in `SYSTEM_AUDIT_RESULTS.json`.

After backing up the local database and refreshing the backend, a real localhost browser check confirmed that the existing dummy login still opens its saved profile and three reports, survives refresh, and denies data access after logout. No private account credentials or data are included in the published assets or this report.
