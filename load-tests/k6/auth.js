import { check, sleep } from "k6";

import { login } from "./lib/api.js";
import { buildOptions, runtimeConfig } from "./lib/config.js";

export const options = buildOptions(1500);

export default function () {
  const token = login();
  check(token, {
    "login returned non-empty token": (value) => Boolean(value),
  });
  sleep(runtimeConfig.sleepSeconds);
}
