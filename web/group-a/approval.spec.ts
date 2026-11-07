import { expect, test } from "@playwright/test";

// Real-stack Group A UI evidence. Run explicitly with playwright.group-a.config.ts.
test("approval gates remain visible on desktop and mobile", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.context().clearCookies();
  await page.goto("/");
  const login = page.getByTestId("login-nurse-a");
  await login.focus();
  await expect(login).toBeFocused();
  await login.click();
  await page.getByTestId("demo-director").getByRole("button", { name: /Demo director/ }).click();
  await page.getByTestId("demo-load").click();
  await expect(page.getByText("P-014 scenario loaded")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("demo-director").getByRole("button", { name: /Demo director/ }).click();
  const queue = await (await page.request.get("/api/queue")).json();
  const visit = queue.patients.find((p: { patient_label: string }) => p.patient_label === "P-014").visit_id;
  const row = page.getByTestId(`row-${visit}`);
  await page.getByTestId(`record-${visit}`).click();
  await page.getByTestId("fill-scenario").click();
  await page.getByTestId("save-vitals").click();
  await expect(page.getByTestId("vitals-saved")).toBeVisible();
  await page.getByRole("button", { name: "Back to the waiting room" }).click();
  await expect(page.getByTestId(`review-${visit}`)).toBeVisible({ timeout: 90_000 });
  await expect(row.locator("[data-colour]")).toHaveAttribute("data-colour", "YELLOW");
  await row.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("pending-yellow.png"), scale: "css" });

  await page.request.post("/api/login-as", { data: { user_id: "mgr-k" } });
  await page.goto("/");
  await expect(page.getByTestId("demo-director")).toHaveCount(0);
  await page.getByTestId(`review-${visit}`).click();
  await expect(page.getByTestId("read-only")).toBeVisible();
  await expect(page.getByTestId("approve")).toHaveCount(0);
  const pending = await (await page.request.get("/api/proposals?status=pending")).json();
  const proposal = pending.find((p: { visit_id: string }) => p.visit_id === visit);
  const refused = await page.request.post(`/api/proposals/${proposal.id}/approve`, {
    data: { colour: "ORANGE", signs_kept: [], override_reason: null },
  });
  expect(refused.status()).toBe(403);
  await expect(page.getByTestId("refused")).toContainText("manager");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.getByTestId("read-only").scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("manager-refused.png"), scale: "css" });

  await page.request.post("/api/login-as", { data: { user_id: "nurse-a" } });
  await page.goto("/");
  await page.getByTestId(`review-${visit}`).click();
  await page.getByTestId("approve").click();
  await expect(page.getByTestId("decided-approved").getByTestId("gates").locator("li[data-done]")).toHaveCount(6, {
    timeout: 30_000,
  });
  await page.getByTestId("decided-approved").getByTestId("gates").scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("nurse-confirmed.png"), scale: "css" });
  await page.keyboard.press("Escape");
  await expect(row.locator("[data-colour]")).toHaveAttribute("data-colour", "ORANGE");
  await row.scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("confirmed-orange.png"), scale: "css" });
  expect(errors).toEqual([]);
});
