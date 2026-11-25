import { expect, test } from "@playwright/test";

test("dashboard overview loads for an authenticated operator", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "Control Plane Overview" })).toBeVisible();
  await expect(page.getByText("Recent Audit Events")).toBeVisible();
});

test("sidebar navigation reaches key operator pages", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/", { waitUntil: "domcontentloaded" });

  await page.getByRole("link", { name: "Approvals" }).click();
  await expect(page).toHaveURL(/\/approvals$/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "Approval Inbox" })).toBeVisible();

  await page.getByRole("link", { name: "Jobs" }).click();
  await expect(page).toHaveURL(/\/jobs$/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "Jobs" })).toBeVisible();

  await page.getByRole("link", { name: "Retention" }).click();
  await expect(page).toHaveURL(/\/retention$/, { timeout: 15_000 });
  await expect(page.locator("main").getByRole("heading", { name: "Retention", exact: true })).toBeVisible();

  await page.getByRole("link", { name: "Audit Integrity" }).click();
  await expect(page).toHaveURL(/\/audit-integrity$/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "Audit Integrity" })).toBeVisible();

  await page.getByRole("link", { name: "Audit Exports" }).click();
  await expect(page).toHaveURL(/\/audit-exports$/, { timeout: 15_000 });
  await expect(page.getByRole("heading", { name: "Audit Exports" })).toBeVisible();
});

test("sign out clears the browser session", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });

  await page.getByRole("button", { name: "Sign out" }).click();

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Access AgentGate" })).toBeVisible();

  const sessionState = await page.evaluate(() => ({
    token: window.localStorage.getItem("agentgate_access_token"),
    user: window.localStorage.getItem("agentgate_current_user"),
  }));
  expect(sessionState.token).toBeNull();
  expect(sessionState.user).toBeNull();
});

test("mobile navigation opens by keyboard and closes after navigation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/", { waitUntil: "domcontentloaded" });

  const menu = page.getByText("AgentGate menu", { exact: true });
  const navigation = page.getByRole("navigation", { name: "Primary" });
  await expect(navigation).toHaveCount(0);
  await menu.focus();
  await menu.press("Enter");
  await expect(navigation.getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
  await menu.press("Escape");
  await expect(menu).toBeFocused();
  await expect(navigation).toHaveCount(0);

  await menu.press("Enter");
  await navigation.getByRole("link", { name: "Approvals" }).click();
  await expect(page.getByRole("heading", { name: "Approval Inbox" })).toBeVisible();
  await expect(navigation).toHaveCount(0);
  await expect(page.getByLabel("Request status")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
