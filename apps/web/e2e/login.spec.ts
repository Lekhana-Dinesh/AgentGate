import { expect, test } from "@playwright/test";

import { loginWithDemoOrConfiguredUser } from "./support/auth";
import { e2eCredentials } from "./support/env";

test("login page renders", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/login", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "Access AgentGate" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeEnabled();
  await expect(page.getByLabel("Tenant slug")).toHaveValue("");
  await expect(page.getByLabel("Email")).toHaveValue("");
  await expect(page.getByLabel("Password")).toHaveValue("");
  await expect(page.locator("body")).not.toContainText(e2eCredentials.password);
});

test("local demo login succeeds", async ({ page }) => {
  test.setTimeout(60_000);
  await loginWithDemoOrConfiguredUser(page);
  await expect(page).not.toHaveURL(/email=|password=/);
  await expect(page.getByText(e2eCredentials.email)).toBeVisible();
});
