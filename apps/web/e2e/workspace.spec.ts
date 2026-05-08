import { expect, test } from "@playwright/test";

test("dashboard overview loads for an authenticated operator", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Control Plane Overview" })).toBeVisible();
  await expect(page.getByText("Total Agents")).toBeVisible();
  await expect(page.getByText("Recent Audit Events")).toBeVisible();
});

test("sidebar navigation reaches key operator pages", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("link", { name: "Approvals" }).click();
  await expect(page).toHaveURL(/\/approvals$/);
  await expect(page.getByRole("heading", { name: "Approval Inbox" })).toBeVisible();

  await page.getByRole("link", { name: "Jobs" }).click();
  await expect(page).toHaveURL(/\/jobs$/);
  await expect(page.getByRole("heading", { name: "Jobs" })).toBeVisible();

  await page.getByRole("link", { name: "Retention" }).click();
  await expect(page).toHaveURL(/\/retention$/);
  await expect(page.getByRole("heading", { name: "Retention" })).toBeVisible();

  await page.getByRole("link", { name: "Audit Integrity" }).click();
  await expect(page).toHaveURL(/\/audit-integrity$/);
  await expect(page.getByRole("heading", { name: "Audit Integrity" })).toBeVisible();

  await page.getByRole("link", { name: "Audit Exports" }).click();
  await expect(page).toHaveURL(/\/audit-exports$/);
  await expect(page.getByRole("heading", { name: "Audit Exports" })).toBeVisible();
});

test("sign out clears the browser session", async ({ page }) => {
  await page.goto("/");

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
