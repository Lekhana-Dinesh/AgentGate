import { check, sleep } from "k6";

import { ensureJobId, getToken, post, get } from "./lib/api.js";
import { buildOptions, runtimeConfig } from "./lib/config.js";

export const options = buildOptions(1500);

export function setup() {
  const token = getToken();
  return {
    token,
    jobId: ensureJobId(token),
  };
}

export default function (context) {
  const listResponse = get("/v1/jobs?limit=10", context.token, "jobs.list");
  check(listResponse, {
    "jobs list returned 200": (res) => res.status === 200,
    "jobs list returned array": (res) => Array.isArray(res.json()),
  });

  const detailResponse = get(`/v1/jobs/${context.jobId}`, context.token, "jobs.detail");
  check(detailResponse, {
    "jobs detail returned 200": (res) => res.status === 200,
    "jobs detail returned job id": (res) => res.json("id") === context.jobId,
  });

  if (__ITER % 5 === 0) {
    const refreshResponse = post(
      "/v1/retention/purge",
      {
        dry_run: true,
        limit: 1,
      },
      context.token,
      "retention.purge.refresh",
    );
    check(refreshResponse, {
      "retention refresh returned 200": (res) => res.status === 200,
      "retention refresh returned job": (res) => Boolean(res.json("job.id")),
    });
  }

  sleep(runtimeConfig.sleepSeconds);
}
