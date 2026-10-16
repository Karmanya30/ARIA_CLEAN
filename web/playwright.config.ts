import { defineConfig } from '@playwright/test'

process.env.ARIA_AUDIT_RUN ??= `${Date.now()}`
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  outputDir: '../.audit/browser-results',
  reporter: [['list'], ['json', { outputFile: '../.audit/browser-results/results.json' }]],
  use: { baseURL: 'http://127.0.0.1:5175', trace: 'retain-on-failure', screenshot: 'only-on-failure', viewport: { width: 1440, height: 1000 } },
  webServer: [
    { command: '..\\.venv\\Scripts\\python.exe ..\\scripts\\audit_server.py', url: 'http://127.0.0.1:8765/api/health', timeout: 180_000, reuseExistingServer: false },
    { command: 'npm run dev -- --host 127.0.0.1 --port 5175 --strictPort', url: 'http://127.0.0.1:5175', env: { ARIA_API_PORT: '8765' }, reuseExistingServer: false },
  ],
})
