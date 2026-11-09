import { expect, test } from "@playwright/test";

test("model location uses recorded provider and reminders do not imply a delay", async ({ page }, info) => {
  // UI fixtures cover free hosted calls, local calls and older traces without metadata. No live model is called.
  const at = new Date().toISOString();
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const variants = [
    { provider: "groq", served_by: "groq", cost_usd: 0 },
    { provider: "ollama", cost_usd: 0 },
    { provider: "ollama_cloud", served_by: "ollama_cloud", cost_usd: 0 },
    { provider: "openrouter", served_by: "Nebius", cost_usd: 0.02 },
    { served_by: "Nebius", cost_usd: 0 },
    { cost_usd: 0 },
  ];
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown;
    if (path === "/api/me") body = { id: "mgr-k", name: "Dir. K", role: "manager", demo: true };
    else if (path === "/api/demo/users") body = [];
    else if (path === "/api/queue") body = {
      as_of: at, notices: [], patients: [{
        visit_id: "fixture-trace", patient_label: "TRACE-001", arrived_at: at, confirmed_colour: "ORANGE",
        target_minutes: 10, minutes_waited: 0, over_target_minutes: 0, pending_proposals: 0,
        last_reading: { obs_id: "Observation/101", effective: at, tews: 6, colour: "ORANGE" },
        flags: [], notices: [{ code: "clinician_reminded", at }],
      }],
    };
    else if (path.includes("/timeline")) body = {
      visit_id: "fixture-trace", chart_id: null, readings: [{
        obs_id: "Observation/101", at, values: {}, tews: 6, colour: "ORANGE", complete: true, missing: [], signs: [],
      }],
    };
    else if (path.includes("/trace")) body = variants.map((model, i) => ({
      step: i + 1, at, kind: "model", server: null, name: `model-${i}`, args_summary: "synthetic fixture",
      result_summary: "checked", latency_ms: 100, tokens_in: 20, tokens_out: 5, cited_ids: [], ...model,
    }));
    else if (path === "/api/proposals") body = [];
    else throw new Error(`Unexpected fixture request: ${path}`);
    await route.fulfill({ json: body });
  });
  await page.goto("/");
  const patient = page.getByRole("button", { name: "TRACE-001", exact: true });
  await patient.focus();
  await expect(patient).toBeFocused();
  await patient.press("Enter");
  await expect(page.getByText("The clinician on duty was reminded to review this second-look suggestion.")).toBeVisible();
  await expect(page.getByText(/has waited a while/)).toHaveCount(0);
  const trace = page.getByTestId("trace");
  const modelRows = trace.locator('li[data-kind="model"]');
  for (const i of [0, 2, 3, 4]) await expect(modelRows.nth(i)).toContainText("remote (synthetic data only)");
  await expect(modelRows.nth(1)).toContainText("language model · local");
  await expect(modelRows.nth(5)).toContainText("provider not recorded");
  await modelRows.first().scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: info.outputPath("provider-labels.png"), scale: "css" });
  await modelRows.last().scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("unknown-provider.png"), scale: "css" });
  await page.getByText("Clinician on duty reminded", { exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("clinician-reminder.png"), scale: "css" });
  expect(errors).toEqual([]);
});
