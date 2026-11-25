import { defineConfig, devices } from "@playwright/test";

const authFile = "e2e/.auth/user.json";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  // The browser scenarios share a seeded tenant and mutate its demo state.
  workers: 1,
  outputDir: "test-results",
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report" }],
  ],
  use: {
    baseURL: process.env.AGENTGATE_E2E_BASE_URL || "http://127.0.0.1:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "setup",
      testMatch: /auth\.setup\.ts/,
      use: {
        ...devices["Desktop Chrome"],
      },
    },
    {
      name: "public",
      testMatch: /login\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
      },
    },
    {
      name: "authenticated",
      dependencies: ["setup"],
      testIgnore: [/auth\.setup\.ts/, /login\.spec\.ts/],
      use: {
        ...devices["Desktop Chrome"],
        storageState: authFile,
      },
    },
  ],
});
