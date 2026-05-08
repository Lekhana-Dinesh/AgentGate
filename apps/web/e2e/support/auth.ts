import { expect, Page } from "@playwright/test";

import { e2eCredentials } from "./env";

export async function loginWithDemoOrConfiguredUser(page: Page) {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Access AgentGate" })).toBeVisible();

  await page.getByLabel("Tenant slug").fill(e2eCredentials.tenantSlug);
  await page.getByLabel("Email").fill(e2eCredentials.email);
  await page.getByLabel("Password").fill(e2eCredentials.password);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "Control Plane Overview" })).toBeVisible();
}
