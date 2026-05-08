import { expect, test, type Locator, type Page } from "@playwright/test";

const secretLikePatterns = [
  /AGENTGATE_[A-Z0-9_]+/,
  /secret_ref:/i,
  /vault:/i,
  /Bearer\s+[A-Za-z0-9._-]+/i,
  /gh[pousr]_[A-Za-z0-9]+/i,
  /xox[baprs]-[A-Za-z0-9-]+/i,
  /AKIA[0-9A-Z]{16}/,
  /-----BEGIN [A-Z ]+PRIVATE KEY-----/,
];

async function expectNoSecretLikeText(locator: Locator) {
  const text = await locator.innerText();
  for (const pattern of secretLikePatterns) {
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
  await page.goto("/onboarding");

  const main = page.locator("main");
  await expect(page.getByRole("heading", { name: "Onboarding" })).toBeVisible();
  await expect(main.getByText("Setup checklist")).toBeVisible();

  const toolsLink = main.locator('a[href="/tools"]').first();
  await expect(toolsLink).toBeVisible();
  await toolsLink.click();
  await expect(page).toHaveURL(/\/tools$/);
  await expect(page.getByRole("heading", { name: "Tools & Connectors" })).toBeVisible();

  await page.goto("/onboarding");
  const settingsLink = page.locator("main").locator('a[href="/settings"]').first();
  await expect(settingsLink).toBeVisible();
  await settingsLink.click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();

  await page.goto("/onboarding");
  const policiesLink = page.locator("main").locator('a[href="/policies"]').first();
  await expect(policiesLink).toBeVisible();
  await policiesLink.click();
  await expect(page).toHaveURL(/\/policies$/);
  await expect(page.getByRole("heading", { name: "Policy Management" })).toBeVisible();
});

test("onboarding dismiss and reset remain safe operator-only actions", async ({ page }) => {
  await page.goto("/onboarding");

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
  await page.goto("/settings");

  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expect(page.getByText("Tenant Profile")).toBeVisible();
  await expect(page.getByText("Operational Links")).toBeVisible();
  await expect(page.getByText("Identity And Notifications")).toBeVisible();
  await expect(page.getByText("Retention And Automation")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open audit exports" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open scheduled tasks" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open retention" })).toBeVisible();
  await expectNoSecretLikeText(page.locator("main"));

  await page.goto("/tools");

  await expect(page.getByRole("heading", { name: "Tools & Connectors" })).toBeVisible();
  await expect(page.getByText("Safe connector posture and metadata control")).toBeVisible();
  await expect(page.getByText("Configured tools and connectors")).toBeVisible();
  await expect(page.getByText("Safe connector metadata templates")).toBeVisible();
  await expect(page.getByText("Configure secrets outside AgentGate")).toBeVisible();
  await expectNoSecretLikeText(page.locator("main"));
});

test("core operator pages render for an authenticated tenant operator", async ({ page }) => {
  await page.goto("/policies");
  await expect(page.getByRole("heading", { name: "Policy Management" })).toBeVisible();
  await expect(page.getByText("Pilot Policy Pack")).toBeVisible();
  await expect(page.getByText("Starter Templates")).toBeVisible();
  await expectNoSecretLikeText(page.locator("main"));

  await page.goto("/users");
  await expect(page.getByRole("heading", { name: "Users & Identity" })).toBeVisible();
  await expect(page.getByText("Identity Lifecycle")).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "User" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Status" })).toBeVisible();

  await page.goto("/scheduled-tasks");
  await expect(page.getByRole("heading", { name: "Scheduled Tasks" })).toBeVisible();
  await expect(page.getByText("Recurring enqueue only")).toBeVisible();
  await expectOneOf(page, [
    { heading: "Last Status" },
    { text: "No scheduled tasks are configured for this tenant yet." },
  ]);

  await page.goto("/audit-integrity");
  await expect(page.getByRole("heading", { name: "Audit Integrity" })).toBeVisible();
  await expect(page.getByText("Checkpoint Snapshot")).toBeVisible();
  await expect(page.getByText("Latest Verification")).toBeVisible();

  await page.goto("/audit-exports");
  await expect(page.getByRole("heading", { name: "Audit Exports" })).toBeVisible();
  await expect(page.getByText("Sanitized export visibility only")).toBeVisible();
  await expectOneOf(page, [
    { heading: "Last Status" },
    { text: "No audit export configs are set up for this tenant yet." },
  ]);

  await page.goto("/retention");
  await expect(page.getByRole("heading", { name: "Retention" })).toBeVisible();
  await expect(page.getByText("Dry-Run Controls")).toBeVisible();
  await expect(page.getByText("Latest Dry-Run")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run dry-run purge" })).toBeVisible();
});
