function envString(name, defaultValue) {
  const value = __ENV[name];
  if (value === undefined || value === "") {
    return defaultValue;
  }
  return value;
}

function envInt(name, defaultValue) {
  const value = parseInt(envString(name, String(defaultValue)), 10);
  if (Number.isNaN(value)) {
    return defaultValue;
  }
  return value;
}

function envBool(name, defaultValue) {
  const value = envString(name, defaultValue ? "true" : "false").toLowerCase();
  return value === "1" || value === "true" || value === "yes" || value === "on";
}

function envFloat(name, defaultValue) {
  const value = parseFloat(envString(name, String(defaultValue)));
  if (Number.isNaN(value)) {
    return defaultValue;
  }
  return value;
}

export const runtimeConfig = {
  baseUrl: envString("AGENTGATE_K6_BASE_URL", "http://127.0.0.1:8000"),
  tenantSlug: envString("AGENTGATE_K6_TENANT_SLUG", "demo-agentgate"),
  email: envString("AGENTGATE_K6_EMAIL", "admin@demo.agentgate.example.com"),
  password: envString("AGENTGATE_K6_PASSWORD", "AgentGate123!"),
  token: envString("AGENTGATE_K6_TOKEN", ""),
  agentId: envString("AGENTGATE_K6_AGENT_ID", ""),
  agentName: envString("AGENTGATE_K6_AGENT_NAME", "SalesProposalAgent"),
  includeApprovalPath: envBool("AGENTGATE_K6_INCLUDE_APPROVAL_PATH", false),
  includeIntegrityVerify: envBool("AGENTGATE_K6_INCLUDE_INTEGRITY_VERIFY", true),
  expectRateLimited: envBool("AGENTGATE_K6_EXPECT_RATE_LIMITED", false),
  vus: envInt("AGENTGATE_K6_VUS", 2),
  duration: envString("AGENTGATE_K6_DURATION", "20s"),
  sleepSeconds: envFloat("AGENTGATE_K6_SLEEP_SECONDS", 1),
};

export function buildOptions(maxP95Ms, overrides = {}) {
  const baseThresholds = {
    checks: ["rate>0.99"],
    http_req_failed: ["rate<0.01"],
    http_req_duration: [`p(95)<${maxP95Ms}`],
  };
  return {
    vus: runtimeConfig.vus,
    duration: runtimeConfig.duration,
    thresholds: Object.assign(baseThresholds, overrides.thresholds || {}),
    summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "max"],
  };
}
