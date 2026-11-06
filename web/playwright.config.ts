import { defineConfig, devices } from "@playwright/test";

// E7-11 against the running compose stack (E7-10: there is no fake API any more). Start it first:
//   docker compose --profile web up -d --build
//   npx playwright test                         # PW_BASE_URL defaults to http://127.0.0.1:3000
const baseURL = process.env.PW_BASE_URL ?? "http://127.0.0.1:3000";

export default defineConfig({
  testDir: "e2e",
  timeout: 180_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL,
    viewport: { width: 1366, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1366, height: 900 } } }],
});
