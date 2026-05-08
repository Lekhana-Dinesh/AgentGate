import { expect, test } from "@playwright/test";

import { e2eCredentials } from "./support/env";

test("login page renders", async ({ page }) => {
  await page.goto("/login");

  await expect(page.getByRole("heading", { name: "Access AgentGate" })).toBeVisible();
  await expect(page.getByLabel("Tenant slug")).toHaveValue(e2eCredentials.tenantSlug);
  await expect(page.getByLabel("Email")).toHaveValue(e2eCredentials.email);
  await expect(page.getByLabel("Password")).toHaveValue(e2eCredentials.password);
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
});

test("local demo login succeeds", async ({ page }) => {
  await page.goto("/login");

  await page.getByLabel("Tenant slug").fill(e2eCredentials.tenantSlug);
  await page.getByLabel("Email").fill(e2eCredentials.email);
  await page.getByLabel("Password").fill(e2eCredentials.password);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Control Plane Overview" })).toBeVisible();
  await expect(page.getByText(e2eCredentials.email)).toBeVisible();
});
