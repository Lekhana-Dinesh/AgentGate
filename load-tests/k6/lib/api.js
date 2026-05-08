import http from "k6/http";
import { check, fail } from "k6";

import { runtimeConfig } from "./config.js";

const JSON_HEADERS = {
  "Content-Type": "application/json",
};

export function apiUrl(path) {
  return `${runtimeConfig.baseUrl}${path}`;
}

function requestParams(token, requestName) {
  const headers = Object.assign({}, JSON_HEADERS);
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return {
    headers,
    tags: { name: requestName },
  };
}

export function get(path, token, requestName) {
  return http.get(apiUrl(path), requestParams(token, requestName));
}

export function post(path, payload, token, requestName) {
  return http.post(
    apiUrl(path),
    JSON.stringify(payload),
    requestParams(token, requestName),
  );
}

export function login() {
  const response = post(
    "/v1/auth/login",
    {
      email: runtimeConfig.email,
      password: runtimeConfig.password,
      tenant_slug: runtimeConfig.tenantSlug,
    },
    null,
    "auth.login",
  );
  const ok = check(response, {
    "login returned 200": (res) => res.status === 200,
    "login returned token": (res) => Boolean(res.json("access_token")),
  });
  if (!ok) {
    fail(`Login failed with status ${response.status}. Check demo seed data and AGENTGATE_K6_* auth settings.`);
  }
  return response.json("access_token");
}

export function getToken() {
  return runtimeConfig.token || login();
}

export function getCurrentUser(token) {
  const response = get("/v1/auth/me", token, "auth.me");
  const ok = check(response, {
    "auth me returned 200": (res) => res.status === 200,
    "auth me returned user id": (res) => Boolean(res.json("id")),
  });
  if (!ok) {
    fail(`Failed to resolve current user with status ${response.status}.`);
  }
  return response.json();
}

export function resolveAgentId(token) {
  if (runtimeConfig.agentId) {
    return runtimeConfig.agentId;
  }

  const response = get("/v1/agents?limit=100", token, "agents.list");
  const ok = check(response, {
    "agents list returned 200": (res) => res.status === 200,
    "agents list returned array": (res) => Array.isArray(res.json()),
  });
  if (!ok) {
    fail(`Failed to list agents with status ${response.status}.`);
  }

  const agents = response.json();
  const matchingAgent = agents.find((agent) => agent.name === runtimeConfig.agentName);
  if (!matchingAgent) {
    fail(
      `Seeded agent '${runtimeConfig.agentName}' was not found. Set AGENTGATE_K6_AGENT_ID or AGENTGATE_K6_AGENT_NAME for your environment.`,
    );
  }
  return matchingAgent.id;
}

export function ensureJobId(token) {
  const listResponse = get("/v1/jobs?limit=1", token, "jobs.list.setup");
  const listOk = check(listResponse, {
    "jobs setup list returned 200": (res) => res.status === 200,
    "jobs setup list returned array": (res) => Array.isArray(res.json()),
  });
  if (!listOk) {
    fail(`Failed to list jobs during setup with status ${listResponse.status}.`);
  }

  const jobs = listResponse.json();
  if (jobs.length > 0) {
    return jobs[0].id;
  }

  const createResponse = post(
    "/v1/retention/purge",
    {
      dry_run: true,
      limit: 1,
    },
    token,
    "retention.purge.setup",
  );
  const createOk = check(createResponse, {
    "retention purge setup returned 200": (res) => res.status === 200,
    "retention purge setup returned job": (res) => Boolean(res.json("job.id")),
  });
  if (!createOk) {
    fail(`Failed to create a setup job with status ${createResponse.status}.`);
  }

  return createResponse.json("job.id");
}

export function getGatewayContext() {
  const token = getToken();
  const currentUser = getCurrentUser(token);
  return {
    token,
    userId: currentUser.id,
    agentId: resolveAgentId(token),
  };
}
