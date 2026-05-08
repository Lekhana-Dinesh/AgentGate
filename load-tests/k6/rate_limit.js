import { check } from "k6";
import { Rate } from "k6/metrics";

import { post } from "./lib/api.js";
import { buildOptions, runtimeConfig } from "./lib/config.js";

const rateLimitedResponses = new Rate("rate_limited_responses");

export const options = buildOptions(1500, {
  thresholds: {
    rate_limited_responses: ["rate>0"],
  },
});

export function setup() {
  if (!runtimeConfig.expectRateLimited) {
    throw new Error(
      "rate_limit.js is opt-in. Enable server-side rate limiting and set AGENTGATE_K6_EXPECT_RATE_LIMITED=true before running this scenario.",
    );
  }
}

export default function () {
  const response = post(
    "/v1/auth/login",
    {
      email: runtimeConfig.email,
      password: runtimeConfig.password,
      tenant_slug: runtimeConfig.tenantSlug,
    },
    null,
    "auth.login.rate_limited",
  );

  rateLimitedResponses.add(response.status === 429);
  check(response, {
    "rate limit returned expected status": (res) => res.status === 200 || res.status === 429,
  });
}
