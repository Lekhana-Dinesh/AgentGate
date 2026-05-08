import fs from "node:fs";
import path from "node:path";

import { test as setup } from "@playwright/test";

import { loginWithDemoOrConfiguredUser } from "./support/auth";

const authFile = path.join("e2e", ".auth", "user.json");

setup("authenticate demo operator", async ({ page }) => {
  fs.mkdirSync(path.dirname(authFile), { recursive: true });
  await loginWithDemoOrConfiguredUser(page);
  await page.context().storageState({ path: authFile });
});
