import { expect, Page } from "@playwright/test";

import { e2eCredentials } from "./env";

async function fillEditableFieldOrAssertValue(page: Page, label: string, value: string) {
  const field = page.getByLabel(label);
  if (await field.isEditable()) {
    await field.fill(value);
    return;
  }
  await expect(field).toHaveValue(value);
}

export async function loginWithDemoOrConfiguredUser(page: Page) {
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Access AgentGate" })).toBeVisible();
  const signInButton = page.getByRole("button", { name: "Sign in" });
  await expect(signInButton).toBeEnabled();

  await fillEditableFieldOrAssertValue(page, "Tenant slug", e2eCredentials.tenantSlug);
  await fillEditableFieldOrAssertValue(page, "Email", e2eCredentials.email);
  await fillEditableFieldOrAssertValue(page, "Password", e2eCredentials.password);
  await signInButton.click();

  await expect(page.getByRole("heading", { name: "Control Plane Overview" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page).not.toHaveURL(/\/login(?:\?|$)/, { timeout: 30_000 });
}
