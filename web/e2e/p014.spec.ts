import { expect, type Page, test } from "@playwright/test";

// The P-014 flow (backlog E7-11): vitals → proposal → manager refused → nurse confirms → ORANGE with a flag.
// Nothing may change colour before the nurse confirms.

async function signInAs(page: Page, id: string) {
  const res = await page.request.post("/api/login-as", { data: { user_id: id } });
  expect(res.ok()).toBeTruthy();
  await page.goto("/");
}

const row = (page: Page) => page.getByTestId("row-v014");

test("P-014: vitals, suggestion, manager refused, nurse confirms ORANGE", async ({ page }) => {
  // First screen: sign in as the nurse by clicking.
  await page.context().clearCookies();
  await page.goto("/");
  await expect(page.getByTestId("demo-badge").first()).toBeVisible();
  await page.getByTestId("login-nurse-a").click();
  await expect(page.getByRole("heading", { name: "Waiting room" })).toBeVisible();

  // Load the scenario: P-014 starts YELLOW with no suggestion.
  await page.getByTestId("demo-load").click();
  await expect(row(page).locator("[data-colour]")).toHaveAttribute("data-colour", "YELLOW");
  await expect(page.getByTestId("review-v014")).toHaveCount(0);

  // Record P-014's next reading through the form.
  await row(page).getByTestId("record-v014").click();
  await page.getByTestId("fill-scenario").click();
  await page.getByTestId("save-vitals").click();
  await expect(page.getByTestId("vitals-saved")).toBeVisible();
  await page.getByRole("button", { name: "Back to the waiting room" }).click();

  // The agent suggests a second look; the colour has NOT changed.
  await expect(page.getByTestId("review-v014")).toBeVisible({ timeout: 30_000 });
  await expect(row(page).locator("[data-colour]")).toHaveAttribute("data-colour", "YELLOW");

  // The manager can read the card but has no approve button; an API attempt is refused (403) and recorded.
  await signInAs(page, "mgr-k");
  await page.getByTestId("review-v014").click();
  const card = page.getByTestId("approval-card");
  await expect(card).toBeVisible();
  await expect(page.getByTestId("approve")).toHaveCount(0);
  await expect(page.getByTestId("read-only")).toBeVisible();
  const proposals = await (await page.request.get("/api/proposals")).json();
  const refused = await page.request.post(`/api/proposals/${proposals[0].id}/approve`, {
    data: { colour: "ORANGE", signs_kept: [], override_reason: null },
  });
  expect(refused.status()).toBe(403);
  await expect(page.getByTestId("refused")).toContainText("manager");
  await expect(row(page).locator("[data-colour]")).toHaveAttribute("data-colour", "YELLOW");

  // The nurse reviews the evidence and the quotes, then confirms.
  await signInAs(page, "nurse-a");
  await page.getByTestId("review-v014").click();
  await expect(page.getByTestId("evidence").locator("tr[data-band-changed]")).toHaveCount(2);
  await expect(page.getByTestId("complaint").locator('mark[data-status="current"]')).toHaveText("Short of breath");
  await expect(page.getByTestId("complaint").locator('mark[data-status="other"]')).toHaveText("My mother had chest pain");
  await page.getByTestId("approve").click();

  // Six gate ticks, P-014 ORANGE with the second-look flag.
  await expect(page.getByTestId("gates").locator("li[data-done]")).toHaveCount(6);
  await expect(page.getByTestId("decided-approved")).toContainText("Nurse A.");
  await page.keyboard.press("Escape");
  await expect(row(page).locator("[data-colour]")).toHaveAttribute("data-colour", "ORANGE");
  await expect(row(page)).toContainText("Second look confirmed");

  // Everything is in the audit log.
  await page.getByRole("button", { name: "Audit log" }).click();
  const audit = page.getByTestId("audit");
  for (const kind of ["vitals_recorded", "proposal_created", "approve_refused", "proposal_approved", "command_done"]) {
    await expect(audit.locator(`tr[data-kind="${kind}"]`).first()).toBeVisible();
  }
});
