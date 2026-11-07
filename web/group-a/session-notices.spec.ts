import { expect, test } from "@playwright/test";

test("manager controls and logout failure/retry preserve session boundaries", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByTestId("login-nurse-a").click();
  const director = page.getByTestId("demo-director");
  await expect(director).toBeVisible();
  await expect(director.getByRole("button", { name: /Demo director/ })).toHaveAttribute("aria-expanded", "false");
  await page.getByTestId("user-switcher").click();
  await page.getByTestId("switch-mgr-k").click();
  await expect(page.getByTestId("user-switcher")).toHaveAccessibleName("User menu for Dir. K");
  await expect(director).toHaveCount(0);
  await expect(page.locator('[data-testid^="row-"]').first()).toBeVisible();
  await expect(page.locator('[data-testid^="record-"]')).toHaveCount(0);
  expect((await page.request.post("/api/demo/scenario", { data: { scenario: "p014" } })).status()).toBe(403);
  await page.screenshot({ path: info.outputPath("manager-board.png"), scale: "css" });

  // Only the failure response is simulated; successful logout and cookie checks use the real API.
  await page.route("**/api/logout", (route) => route.fulfill({
    status: 503, contentType: "application/json",
    body: JSON.stringify({ error: { code: "unavailable", message: "Temporary connection failure." } }),
  }));
  await page.getByTestId("user-switcher").click();
  await page.getByTestId("logout").focus();
  await expect(page.getByTestId("logout")).toBeFocused();
  await page.screenshot({ path: info.outputPath("logout-menu.png"), scale: "css" });
  await page.getByTestId("logout").click();
  await expect(page.getByText("Could not sign out", { exact: true })).toBeVisible();
  expect((await page.request.get("/api/me")).status()).toBe(200);
  await page.screenshot({ path: info.outputPath("logout-retry.png"), scale: "css" });
  await page.unroute("**/api/logout");
  await page.getByTestId("user-switcher").click();
  await page.getByTestId("logout").click();
  await expect(page.getByTestId("login-nurse-a")).toBeVisible();
  expect((await page.request.get("/api/me")).status()).toBe(401);
  expect((await page.request.get("/api/queue")).status()).toBe(401);
  await page.reload();
  await expect(page.getByTestId("login-nurse-a")).toBeVisible();
  await expect(page.locator('[data-testid^="row-"]')).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("signed-out.png"), scale: "css" });
  expect(errors).toEqual([]);
});

test("new notice codes give staff actionable wording", async ({ page }, info) => {
  // Contract-shaped UI fixtures, not simulated backend outcomes or model evidence.
  await page.route("**/api/queue", async (route) => {
    const response = await route.fetch();
    const queue = await response.json();
    queue.notices = [
      { code: "command_abandoned" }, { code: "agent_failed" }, { code: "data_incomplete" },
    ];
    await route.fulfill({ response, json: queue });
  });
  await page.goto("/");
  await page.getByTestId("login-mgr-k").click();
  await expect(page.getByText("The confirmed second look was not recorded", { exact: true })).toBeVisible();
  await expect(page.getByText("The watch agent could not finish a check", { exact: true })).toBeVisible();
  await expect(page.getByText("Some visit data is missing", { exact: true })).toBeVisible();
  await expect(page.getByTestId("demo-director")).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: info.outputPath("new-notices.png"), scale: "css" });
});
