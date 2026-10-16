import { defineConfig } from '@playwright/test'

process.env.ARIA_AUDIT_RUN ??= `accounts-${Date.now()}`
export default defineConfig({
  testDir: './e2e-accounts', workers: 1, fullyParallel: false, timeout: 90_000,
  expect: { timeout: 15_000 }, outputDir: '../.audit/account-browser-results',
  reporter: [['list'], ['json', { outputFile: '../.audit/account-browser-results/results.json' }]],
  use: { baseURL: 'http://127.0.0.1:5177', trace: 'retain-on-failure', screenshot: 'only-on-failure', viewport: { width: 1440, height: 1000 } },
  webServer: [
    { command: '..\\.venv\\Scripts\\python.exe ..\\scripts\\audit_server.py', url: 'http://127.0.0.1:8767/api/health', timeout: 180_000, reuseExistingServer: false,
      env: { ARIA_AUTH_MODE: 'accounts', ARIA_AUTH_ALLOW_SIGNUP: '1', ARIA_APP_ORIGIN: 'http://127.0.0.1:5177', ARIA_AUDIT_GOOGLE: '1', ARIA_AUDIT_PORT: '8767' } },
    { command: 'npm run dev -- --host 127.0.0.1 --port 5177 --strictPort', url: 'http://127.0.0.1:5177', env: { ARIA_API_PORT: '8767' }, reuseExistingServer: false },
  ],
})
