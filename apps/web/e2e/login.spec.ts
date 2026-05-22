import { expect, test } from "@playwright/test";

import { e2eCredentials } from "./support/env";

test("login page renders", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/login", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "Access AgentGate" })).toBeVisible();
  await expect(page.getByLabel("Tenant slug")).toHaveValue(e2eCredentials.tenantSlug);
  await expect(page.getByLabel("Email")).toHaveValue(e2eCredentials.email);
  await expect(page.getByLabel("Password")).toHaveValue(e2eCredentials.password);
  await expect(page.getByRole("button", { name: "Sign in" })).toBeEnabled();
});

test("local demo login succeeds", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/login", { waitUntil: "domcontentloaded" });

  const signInButton = page.getByRole("button", { name: "Sign in" });
  await expect(signInButton).toBeEnabled();

  const tenantSlugField = page.getByLabel("Tenant slug");
  if (await tenantSlugField.isEditable()) {
    await tenantSlugField.fill(e2eCredentials.tenantSlug);
  } else {
    await expect(tenantSlugField).toHaveValue(e2eCredentials.tenantSlug);
  }

  const emailField = page.getByLabel("Email");
  if (await emailField.isEditable()) {
    await emailField.fill(e2eCredentials.email);
  } else {
    await expect(emailField).toHaveValue(e2eCredentials.email);
  }

  const passwordField = page.getByLabel("Password");
  if (await passwordField.isEditable()) {
    await passwordField.fill(e2eCredentials.password);
  } else {
    await expect(passwordField).toHaveValue(e2eCredentials.password);
  }

  await signInButton.click();

  await expect(page.getByRole("heading", { name: "Control Plane Overview" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page).not.toHaveURL(/\/login(?:\?|$)/, { timeout: 30_000 });
  await expect(page).not.toHaveURL(/email=|password=/);
  await expect(page.getByText(e2eCredentials.email)).toBeVisible();
});
