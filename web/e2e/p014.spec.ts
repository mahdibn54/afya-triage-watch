import { expect, type Page, test } from "@playwright/test";

// The P-014 flow (backlog E7-11) on the real stack: vitals → proposal → manager refused → nurse confirms → ORANGE with
// a flag. Nothing may change colour before the nurse confirms. The visit id comes from HAPI, so rows are found by the
// label. Runs with the language model on or off: the quote highlights are checked only when the sign mapper ran.

async function signInAs(page: Page, id: string) {
  const res = await page.request.post("/api/login-as", { data: { user_id: id } });
  expect(res.ok()).toBeTruthy();
  await page.goto("/");
}

async function p014Visit(page: Page): Promise<string> {
  const queue = await (await page.request.get("/api/queue")).json();
  const p = queue.patients.find((x: { patient_label: string | null }) => x.patient_label === "P-014");
  expect(p, "P-014 is in the waiting room").toBeTruthy();
  return p.visit_id;
}

test("P-014: vitals, suggestion, manager refused, nurse confirms ORANGE", async ({ page }) => {
  // First screen: sign in as the nurse by clicking.
  await page.context().clearCookies();
  await page.goto("/");
  await expect(page.getByTestId("demo-badge").first()).toBeVisible();
  await page.getByTestId("login-nurse-a").click();
  await expect(page.getByRole("heading", { name: "Waiting room" })).toBeVisible();

  // Load the scenario: P-014 starts YELLOW with no suggestion.
  await page.getByTestId("demo-director").getByRole("button", { name: /Demo director/ }).click();
  await page.getByTestId("demo-load").click();
  await expect(page.getByText("P-014 scenario loaded")).toBeVisible({ timeout: 30_000 });
  const visit = await p014Visit(page);
  const row = page.getByTestId(`row-${visit}`);
  await expect(row.locator("[data-colour]")).toHaveAttribute("data-colour", "YELLOW");
  await expect(page.getByTestId(`review-${visit}`)).toHaveCount(0);

  // Record P-014's next reading through the form.
  await page.getByTestId(`record-${visit}`).click();
  await page.getByTestId("fill-scenario").click();
  await page.getByTestId("save-vitals").click();
  await expect(page.getByTestId("vitals-saved")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Back to the waiting room" }).click();

  // The agent suggests a second look; the colour has NOT changed.
  await expect(page.getByTestId(`review-${visit}`)).toBeVisible({ timeout: 90_000 });
  await expect(row.locator("[data-colour]")).toHaveAttribute("data-colour", "YELLOW");

  // The manager can read the card but has no approve button; an API attempt is refused (403) and recorded.
  await signInAs(page, "mgr-k");
  await page.getByTestId(`review-${visit}`).click();
  await expect(page.getByTestId("approval-card")).toBeVisible();
  await expect(page.getByTestId("approve")).toHaveCount(0);
  await expect(page.getByTestId("read-only")).toBeVisible();
  const pending = await (await page.request.get("/api/proposals?status=pending")).json();
  const proposal = pending.find((x: { visit_id: string }) => x.visit_id === visit);
  expect(proposal).toBeTruthy();
  const refused = await page.request.post(`/api/proposals/${proposal.id}/approve`, {
    data: { colour: "ORANGE", signs_kept: [], override_reason: null },
  });
  expect(refused.status()).toBe(403);
  await expect(page.getByTestId("refused")).toContainText("manager");
  await page.keyboard.press("Escape");
  await expect(row.locator("[data-colour]")).toHaveAttribute("data-colour", "YELLOW");

  // The nurse reviews the evidence (and the quotes, when the sign mapper ran), then confirms.
  await signInAs(page, "nurse-a");
  await page.getByTestId(`review-${visit}`).click();
  await expect(page.getByTestId("evidence").locator("tr[data-band-changed]")).toHaveCount(2);
  await expect(page.getByTestId("complaint")).toContainText("Short of breath since morning.");
  if (proposal.signs_verdict === "found") {
    await expect(page.getByTestId("complaint").locator('mark[data-status="current"]').first()).toBeVisible();
  } else {
    await expect(page.getByText("Phrases were not matched")).toBeVisible();
  }
  await page.getByTestId("approve").click();

  // Six gate ticks, P-014 ORANGE with the second-look flag.
  await expect(page.getByTestId("decided-approved").getByTestId("gates").locator("li[data-done]")).toHaveCount(6, {
    timeout: 30_000,
  });
  await expect(page.getByTestId("decided-approved")).toContainText("Nurse A.");
  await page.keyboard.press("Escape");
  await expect(row.locator("[data-colour]")).toHaveAttribute("data-colour", "ORANGE");
  await expect(row).toContainText("Second look confirmed");

  // Everything is in the audit log.
  await page.getByRole("button", { name: "Audit log" }).click();
  const audit = page.getByTestId("audit");
  for (const kind of ["record_vitals", "agent_step", "approve_refused", "proposal_approved", "command_done"]) {
    await expect(audit.locator(`tr[data-kind="${kind}"]`).first()).toBeVisible();
  }
});
