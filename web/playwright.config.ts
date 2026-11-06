import { defineConfig, devices } from "@playwright/test";

// E7-11. Default: starts the UI on the fake API (FAKE_API=1). Against the compose stack (after E7-10):
//   PW_BASE_URL=http://127.0.0.1:3000 npx playwright test
const external = process.env.PW_BASE_URL;
const port = 3005;

export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: external ?? `http://localhost:${port}`,
    viewport: { width: 1366, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1366, height: 900 } } }],
  webServer: external
    ? undefined
    : {
        command: `npm run dev:fake -- -p ${port}`,
        url: `http://localhost:${port}/api/healthz`,
        reuseExistingServer: false,
        timeout: 120_000,
      },
});
