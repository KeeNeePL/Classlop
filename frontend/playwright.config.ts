import { defineConfig } from '@playwright/test';

// The dev server on :4201 proxies to a backend on :8001 that has the Teacher signed in already,
// so these never meet the compose :4200 and :8000.
export default defineConfig({
  testDir: 'e2e',
  use: { baseURL: 'http://localhost:4201' },
  webServer: [
    {
      command:
        'uv run --project ../backend uvicorn --app-dir ../backend/tests e2e_app:create --factory --port 8001',
      url: 'http://localhost:8001/api/me',
      reuseExistingServer: !process.env['CI'],
    },
    {
      command: 'npm start -- --port 4201 --proxy-config e2e/proxy.json',
      url: 'http://localhost:4201',
      reuseExistingServer: !process.env['CI'],
    },
  ],
});
