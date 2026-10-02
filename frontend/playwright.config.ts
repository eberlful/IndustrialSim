import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  use: {
    baseURL: 'http://127.0.0.1:18765',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {},
  },
  webServer: {
    command: process.env.INDUSTRIALSIM_PYTHON
      ? `"${process.env.INDUSTRIALSIM_PYTHON}" tests/serve.py`
      : 'uv run --project .. --no-default-groups --extra frontend python tests/serve.py',
    url: 'http://127.0.0.1:18765/api/project',
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
