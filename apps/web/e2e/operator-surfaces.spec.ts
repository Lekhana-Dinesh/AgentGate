import { expect, test, type Locator, type Page } from "@playwright/test";

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

async function expectOneOf(page: Page, options: { heading?: string; text?: string }[]) {
  for (const option of options) {
    if (option.heading) {
      const heading = page.getByRole("columnheader", { name: option.heading });
      if (await heading.count()) {
        await expect(heading).toBeVisible();
        return;
      }
    }
    if (option.text) {
      const text = page.getByText(option.text);
      if (await text.count()) {
        await expect(text).toBeVisible();
        return;
      }
    }
  }
  throw new Error(
    `Expected one of the following page markers: ${options
      .map((option) => option.heading || option.text)
      .filter(Boolean)
      .join(", ")}`,
  );
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
  await expect(page.getByText("Demo-safe by default")).toBeVisible();

  await page.getByRole("button", { name: "Run governed GitHub workflow" }).click();

  await expect(page.getByText("Governed run completed")).toBeVisible();
  await expect(page.getByText("Policy flagged the request before execution")).toBeVisible();
  await expect(page.getByText("Approved by reviewer@demo.agentgate.example.com")).toBeVisible();
  await expect(page.getByText("Operator-visible event trail")).toBeVisible();
  await expect(page.getByText("Demo-safe execution is active.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open trace replay" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open approved request" })).toBeVisible();
});
