import { expect, Page } from "@playwright/test";

import { e2eCredentials } from "./env";

export async function loginWithDemoOrConfiguredUser(page: Page) {
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Access AgentGate" })).toBeVisible();
  const signInButton = page.getByRole("button", { name: "Sign in" });
  await expect(signInButton).toBeEnabled();

  await page.getByLabel("Tenant slug").fill(e2eCredentials.tenantSlug);
  await page.getByLabel("Email").fill(e2eCredentials.email);
  await page.getByLabel("Password").fill(e2eCredentials.password);
  await signInButton.click();

  await expect(page.getByRole("heading", { name: "Control Plane Overview" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page).not.toHaveURL(/\/login(?:\?|$)/, { timeout: 30_000 });
}
