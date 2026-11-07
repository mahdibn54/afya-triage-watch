import { expect, test } from "@playwright/test";

// Run explicitly against an isolated, seeded stack; this test never loads P-014 or changes a patient's readings.
test("twenty seeded patients are usable on desktop and mobile", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  const login = page.getByTestId("login-nurse-a");
  await login.focus();
  await expect(login).toBeFocused();
  await login.click();
  await expect(page.locator('[data-testid^="row-"]').filter({ hasText: "SYN-" })).toHaveCount(20, { timeout: 60_000 });
  await page.getByTestId("demo-director").getByRole("button", { name: /Demo director/ }).click();
  const response = await page.request.get("/api/queue");
  expect(response.ok()).toBeTruthy();
  const queue = await response.json();
  const seeded = queue.patients.filter((p: { patient_label: string | null }) => p.patient_label?.startsWith("SYN-"));
  expect(seeded).toHaveLength(20);
  for (const patient of seeded) {
    expect(patient.patient_label).toMatch(/^SYN-b\d\d-/);
    await expect(page.getByTestId(`row-${patient.visit_id}`)).toContainText(patient.patient_label);
  }
  const patient = queue.patients.find((p: { patient_label: string }) => p.patient_label === "SYN-b01-yellow-orange");
  const firstVisit = queue.patients.find((p: { patient_label: string }) => p.patient_label === "SYN-b13-first-visit");
  expect(firstVisit.confirmed_colour).toBeNull();
  expect(patient.confirmed_colour).toBe("YELLOW");
  await expect(page.getByTestId(`row-${patient.visit_id}`).locator("[data-colour]")).toHaveAttribute("data-colour", "YELLOW");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: info.outputPath("seeded-board.png"), scale: "css" });
  await page.screenshot({ path: info.outputPath("seeded-board-full.png"), fullPage: true, scale: "css" });
  const row = page.getByTestId(`row-${patient.visit_id}`);
  await row.getByRole("button").first().focus();
  await expect(row.getByRole("button").first()).toBeFocused();
  await row.getByRole("button").first().click();
  await expect(page.getByRole("heading", { name: patient.patient_label, exact: true })).toBeVisible();
  await expect(page.getByText("No second look suggested", { exact: true })).toBeVisible();
  await expect(page.getByText("No agent run for this reading yet.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Record vitals", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: info.outputPath("seeded-patient.png"), scale: "css" });
  expect(errors).toEqual([]);
});
