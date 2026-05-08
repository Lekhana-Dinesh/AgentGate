import { check, sleep } from "k6";

import { getGatewayContext, post } from "./lib/api.js";
import { buildOptions, runtimeConfig } from "./lib/config.js";

export const options = buildOptions(2000);

const HAPPY_PATH_PAYLOAD = {
  original_intent: "Review the current Salesforce account record before drafting a renewal plan.",
  tool_name: "Salesforce",
  action_name: "read_account",
  arguments: {
    account_id: "acc_acme_001",
  },
  data_classifications: ["customer_internal"],
  metadata: {
    load_test: "k6",
    scenario: "gateway_happy_path",
  },
};

const APPROVAL_PATH_PAYLOAD = {
  original_intent: "Approve a larger renewal discount for a high-value customer after manual review.",
  tool_name: "PricingDB",
  action_name: "apply_discount",
  arguments: {
    discount_percent: 30,
    sku: "renewal-pro",
  },
  data_classifications: ["pricing_internal"],
  metadata: {
    load_test: "k6",
    scenario: "gateway_approval_path",
  },
};

export function setup() {
  return getGatewayContext();
}

function runHappyPath(context) {
  const response = post(
    "/v1/gateway/tool-call",
    Object.assign({ agent_id: context.agentId }, HAPPY_PATH_PAYLOAD),
    context.token,
    "gateway.happy",
  );
  check(response, {
    "gateway happy returned 200": (res) => res.status === 200,
    "gateway happy allowed execution": (res) => res.json("decision") === "allow",
    "gateway happy executed": (res) => res.json("executed") === true,
    "gateway happy status executed": (res) => res.json("status") === "executed",
  });
}

function runApprovalPath(context) {
  const response = post(
    "/v1/gateway/tool-call",
    Object.assign({ agent_id: context.agentId }, APPROVAL_PATH_PAYLOAD),
    context.token,
    "gateway.approval",
  );
  check(response, {
    "gateway approval returned 200": (res) => res.status === 200,
    "gateway approval required review": (res) => res.json("decision") === "require_approval",
    "gateway approval not executed": (res) => res.json("executed") === false,
    "gateway approval status pending": (res) => res.json("status") === "pending_approval",
  });
}

export default function (context) {
  if (runtimeConfig.includeApprovalPath && __ITER % 4 === 0) {
    runApprovalPath(context);
  } else {
    runHappyPath(context);
  }
  sleep(runtimeConfig.sleepSeconds);
}
