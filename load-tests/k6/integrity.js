import { check, sleep } from "k6";

import { getToken, get, post } from "./lib/api.js";
import { buildOptions, runtimeConfig } from "./lib/config.js";

export const options = buildOptions(2000);

export function setup() {
  return {
    token: getToken(),
  };
}

export default function (context) {
  const statusResponse = get("/v1/audit-integrity/status", context.token, "audit_integrity.status");
  check(statusResponse, {
    "integrity status returned 200": (res) => res.status === 200,
    "integrity status returned total events": (res) => typeof res.json("total_events") === "number",
  });

  if (runtimeConfig.includeIntegrityVerify) {
    const verifyResponse = post(
      "/v1/audit-integrity/verify",
      {},
      context.token,
      "audit_integrity.verify",
    );
    check(verifyResponse, {
      "integrity verify returned 200": (res) => res.status === 200,
      "integrity verify returned chain_valid": (res) => typeof res.json("chain_valid") === "boolean",
    });
  }

  sleep(runtimeConfig.sleepSeconds);
}
