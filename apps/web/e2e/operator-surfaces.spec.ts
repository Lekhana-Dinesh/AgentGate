import { expect, test, type Locator } from "@playwright/test";
import { e2eCredentials } from "./support/env";

const strictSecretLikePatterns = [
  /AGENTGATE_[A-Z0-9_]+/,
  /secret_ref:/i,
  /vault:/i,
  /Bearer\s+[A-Za-z0-9._-]+/i,
  /gh[pousr]_[A-Za-z0-9]+/i,
  /xox[baprs]-[A-Za-z0-9-]+/i,
  /AKIA[0-9A-Z]{16}/,
  /-----BEGIN [A-Z ]+PRIVATE KEY-----/,
];

const secretValuePatterns = [
  /secret_ref:/i,
  /vault:/i,
  /Bearer\s+[A-Za-z0-9._-]+/i,
  /gh[pousr]_[A-Za-z0-9]+/i,
  /xox[baprs]-[A-Za-z0-9-]+/i,
  /AKIA[0-9A-Z]{16}/,
  /-----BEGIN [A-Z ]+PRIVATE KEY-----/,
];

async function expectNoStrictSecretLikeText(locator: Locator) {
  const text = await locator.innerText();
  for (const pattern of strictSecretLikePatterns) {
    expect(text).not.toMatch(pattern);
  }
}

async function expectNoSecretValues(locator: Locator) {
  const text = await locator.innerText();
  for (const pattern of secretValuePatterns) {
    expect(text).not.toMatch(pattern);
  }
}

test("onboarding renders checklist and links to the first governed workflow surfaces", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/onboarding", { waitUntil: "domcontentloaded" });

  const main = page.locator("main");
  await expect(page.getByRole("heading", { name: "Onboarding" })).toBeVisible();
  const resetButton = page.getByRole("button", { name: "Reset walkthrough" });
  if (await resetButton.isVisible().catch(() => false)) {
    await resetButton.click();
  }

  const toolsLink = main.locator('a[href="/tools"]').first();
  await expect(toolsLink).toBeVisible({ timeout: 15_000 });
  await toolsLink.click();
  await page.waitForURL(/\/tools$/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "Tools & Connectors" })).toBeVisible();

  await page.goto("/onboarding", { waitUntil: "domcontentloaded" });
  const settingsLink = page.locator("main").locator('a[href="/settings"]').first();
  await expect(settingsLink).toBeVisible({ timeout: 15_000 });
  await settingsLink.click();
  await page.waitForURL(/\/settings$/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();

  await page.goto("/onboarding", { waitUntil: "domcontentloaded" });
  const policiesLink = page.locator("main").locator('a[href="/policies"]').first();
  await expect(policiesLink).toBeVisible({ timeout: 15_000 });
  await policiesLink.click();
  await page.waitForURL(/\/policies$/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "Policy Management" })).toBeVisible();
});

test("onboarding dismiss and reset remain safe operator-only actions", async ({ page }) => {
  await page.goto("/onboarding", { waitUntil: "domcontentloaded" });

  await expect(page.getByText("Setup checklist")).toBeVisible();

  const dismissButton = page.getByRole("button", { name: "Dismiss" });
  const resetButton = page.getByRole("button", { name: "Reset walkthrough" });

  if (await resetButton.isVisible().catch(() => false)) {
    await resetButton.click();
    await expect(dismissButton).toBeVisible();
  }

  await dismissButton.click();
  await expect(resetButton).toBeVisible();

  await resetButton.click();
  await expect(dismissButton).toBeVisible();
});

test("settings and tools pages render safe operator visibility without secret-like values", async ({ page }) => {
  await page.goto("/settings", { waitUntil: "domcontentloaded" });

  const main = page.locator("main");
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expect(main.getByText("Tenant Profile", { exact: true })).toBeVisible();
  await expect(main.getByText("Operational Links", { exact: true })).toBeVisible();
  await expect(main.getByText("Identity And Notifications", { exact: true })).toBeVisible();
  await expect(main.getByText("Retention And Automation", { exact: true })).toBeVisible();
  await expect(main.getByRole("link", { name: "Open audit exports" }).first()).toBeVisible();
  await expect(main.getByRole("link", { name: "Open scheduled tasks" }).first()).toBeVisible();
  await expect(main.getByRole("link", { name: "Open retention" }).first()).toBeVisible();
  await expectNoStrictSecretLikeText(main);

  await page.goto("/tools", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "Tools & Connectors" })).toBeVisible();
  await expect(page.getByText("Safe connector posture and metadata control")).toBeVisible();
  await expect(page.getByText("Configured tools and connectors")).toBeVisible();
  await expect(page.getByText("Safe connector metadata templates")).toBeVisible();
  await expect(page.getByText("Configure secrets outside AgentGate")).toBeVisible();
  const githubRow = page.locator("tbody tr").filter({ has: page.getByText("GitHub") }).first();
  await expect(githubRow).toBeVisible();
  await githubRow.getByRole("button", { name: /Edit safe metadata|Review metadata|Reviewing/ }).click();
  const githubGuidancePanel = page.locator("div").filter({
    has: page.getByRole("heading", { name: "Safe live-connector setup guidance" }),
  }).filter({
    has: page.getByText("Validation guidance", { exact: true }),
  }).last();
  await expect(
    githubGuidancePanel.getByRole("heading", { name: "Safe live-connector setup guidance" }),
  ).toBeVisible();
  await expect(githubGuidancePanel).toContainText("Demo-safe mock is active");
  await expect(githubGuidancePanel).toContainText("AGENTGATE_GITHUB_TOKEN");
  await expectNoSecretValues(page.locator("main"));
});

test("core operator pages render for an authenticated tenant operator", async ({ page }) => {
  await page.goto("/policies", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Policy Management" })).toBeVisible();
  await expect(page.getByText("Pilot Policy Pack")).toBeVisible();
  await expect(page.getByText("Starter Templates")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Policy Simulation", exact: true })).toBeVisible();
  await expect(page.getByText("Simulation only. No external tool is executed, no approval is created, and no job is enqueued.")).toBeVisible();

  await page.goto("/users", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Users & Identity" })).toBeVisible();
  await expect(page.getByText("Identity Lifecycle")).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "User" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Status" })).toBeVisible();

  await page.goto("/scheduled-tasks", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Scheduled Tasks" })).toBeVisible();
  await expect(page.getByText("Recurring enqueue only")).toBeVisible();

  await page.goto("/audit-integrity", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Audit Integrity" })).toBeVisible();
  await expect(page.getByText("Checkpoint Snapshot")).toBeVisible();
  await expect(page.getByText("Latest Verification")).toBeVisible();

  await page.goto("/audit-exports", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Audit Exports" })).toBeVisible();
  await expect(page.getByText("Sanitized export visibility only")).toBeVisible();

  await page.goto("/retention", { waitUntil: "domcontentloaded" });
  await expect(page.locator("main").getByRole("heading", { name: "Retention", exact: true })).toBeVisible();
  await expect(page.getByText("Dry-Run Controls")).toBeVisible();
  await expect(page.getByText("Latest Dry-Run")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run dry-run purge" })).toBeVisible();
});

test("policy simulation runs as a dry-run and shows a matched-policy outcome", async ({ page }) => {
  await page.goto("/policies", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "Policy Simulation", exact: true })).toBeVisible();
  await expect(
    page.getByText("Simulation only. No external tool is executed, no approval is created, and no job is enqueued."),
  ).toBeVisible();

  const runButton = page.getByRole("button", { name: "Run policy simulation" });
  await expect(runButton).toBeEnabled();

  await page.getByLabel("Tool", { exact: true }).selectOption("PricingDB");
  await page.getByLabel("Action name").fill("apply_discount");
  await page
    .getByLabel("Original intent")
    .fill("Review pricing guidance for an internal renewal proposal.");
  await page.getByLabel("Data classifications").fill("internal_pricing");
  await page.getByLabel("Arguments JSON").fill('{\n  "discount_percent": 30,\n  "sku": "renewal-pro"\n}');

  await runButton.click();

  await expect(page.getByText("Matched policies")).toBeVisible();
  await expect(page.getByText("Major decision factors")).toBeVisible();
  await expect(page.getByText("Dry-run guarantees")).toBeVisible();
  await expect(
    page.getByText(/Matched saved policy "Require approval for discount above 20 percent"/),
  ).toBeVisible();
  await expect(page.getByText("Simulation only: AgentGate would require approval for this request.")).toBeVisible();
});

test("governed GitHub demo shows approval, execution, and evidence without requiring a live connector", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/demo", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "Governed GitHub workflow" })).toBeVisible();
  await expect(page.getByText("Demo-safe connector required")).toBeVisible();

  await page.getByRole("button", { name: "Run governed GitHub workflow" }).click();

  await expect(page.getByRole("heading", { name: /Governed run completed|Approved execution queued/ })).toBeVisible();
  await expect(page.getByText("Policy flagged the request before execution")).toBeVisible();
  await expect(page.getByText("Approved by reviewer@demo.agentgate.example.com")).toBeVisible();
  await expect(page.getByText("Operator-visible event trail")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open trace replay" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open approved request" })).toBeVisible();
  await page.getByRole("link", { name: "Open trace replay" }).click();
  await expect(page).toHaveURL(/\/traces\/[\w-]+$/);
  await expect(async () => {
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.getByText(/Approved execution completed for GitHub/)).toBeVisible({ timeout: 1_500 });
  }).toPass({ timeout: 15_000 });
});

test("operator approves and rejects separate synthetic requests with trace evidence", async ({ page, request }) => {
  test.setTimeout(60_000);
  const api = process.env.AGENTGATE_E2E_API_BASE_URL || "http://127.0.0.1:8000";
  const login = await request.post(`${api}/v1/auth/login`, { data: {
    email: e2eCredentials.email,
    password: e2eCredentials.password,
    tenant_slug: e2eCredentials.tenantSlug,
  } });
  expect(login.ok()).toBeTruthy();
  const { access_token } = await login.json();
  const headers = { Authorization: `Bearer ${access_token}` };

  for (const decision of ["approve", "reject"]) {
    await page.goto("/demo");
    await page.getByRole("button", { name: "Run sales workflow" }).click();
    const traceLink = page.getByRole("link", { name: "Open trace", exact: true });
    await expect(traceLink).toHaveAttribute("href", /^\/traces\/[\w-]+$/);
    const tracePath = await traceLink.getAttribute("href");

    await page.goto("/approvals");
    const review = page.getByRole("article")
      .filter({ has: page.locator(`a[href="${tracePath}"]`) })
      .filter({ has: page.getByRole("heading", { name: "Email.send_external_email", exact: true }) });
    const comment = decision === "approve" ? "Reviewed synthetic pricing." : "Keep synthetic pricing internal.";
    await review.getByLabel("Reviewer comment (optional)").fill(comment);
    await review.getByRole("button", { name: decision === "approve" ? "Approve and execute" : "Reject", exact: true }).click();
    const approved = decision === "approve";
    await expect(page.getByRole("status").filter({ hasText: approved ? "Request approved." : "Request rejected." })).toBeVisible();
    await expect(review).toHaveCount(0);
    await page.getByLabel("Request status").selectOption(approved ? "approved" : "rejected");
    await expect(review.getByText(comment, { exact: true })).toBeVisible();
    await review.getByRole("link", { name: "View trace" }).click();
    await expect(page).toHaveURL(/\/traces\/[\w-]+$/);
    await expect.poll(async () => {
      const trace = await request.get(`${api}/v1${tracePath}`, { headers });
      const { status, steps } = await trace.json();
      const stepNumbers = steps.map((step: { step_number: number }) => step.step_number);
      return {
        status,
        discountExecuted: steps.some((step: { content: string }) => step.content.includes("Approved execution completed for PricingDB")),
        uniqueSteps: new Set(stepNumbers).size === stepNumbers.length,
      };
    }, { timeout: 15_000 }).toEqual({
      status: approved ? "completed" : "blocked",
      discountExecuted: true,
      uniqueSteps: true,
    });
    await page.reload();
    await expect(page.getByText(approved ? /Approved execution completed for Email/ : /Execution ended because the approval request was rejected/)).toBeVisible();
  }
});
