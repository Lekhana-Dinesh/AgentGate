import { check, sleep } from "k6";
import http from "k6/http";

import { buildOptions, runtimeConfig } from "./lib/config.js";

export const options = buildOptions(1000, {
  thresholds: {
    http_req_duration: ["p(95)<1000"],
  },
});

export default function () {
  const healthResponse = http.get(`${runtimeConfig.baseUrl}/health`, {
    tags: { name: "health" },
  });
  check(healthResponse, {
    "health returned 200": (res) => res.status === 200,
  });

  const readyResponse = http.get(`${runtimeConfig.baseUrl}/ready`, {
    tags: { name: "ready" },
  });
  check(readyResponse, {
    "ready returned 200": (res) => res.status === 200,
  });

  sleep(runtimeConfig.sleepSeconds);
}
