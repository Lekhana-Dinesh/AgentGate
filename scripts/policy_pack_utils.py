from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PACK_PATH = REPO_ROOT / "policy-packs" / "pilot-default" / "policies.json"

ALLOWED_POLICY_FIELDS = {
    "name",
    "description",
    "enabled",
    "severity",
    "decision",
    "conditions",
}
ALLOWED_CONDITION_FIELDS = {"match", "rules"}
ALLOWED_RULE_FIELDS = {"field", "operator", "value"}
ALLOWED_SEVERITIES = {"low", "medium", "high", "critical"}
ALLOWED_DECISIONS = {"allow", "block", "require_approval", "redact"}
ALLOWED_MATCH_VALUES = {"all", "any"}
ALLOWED_OPERATORS = {"equals", "contains", "greater_than"}

TEXT_FIELDS = {
    "tool_name",
    "action_name",
    "recipient_domain",
    "environment",
    "repo_trust",
}
LIST_TEXT_FIELDS = {"data_classification"}
NUMERIC_FIELDS = {"amount", "discount_percent", "risk_score", "row_count"}
BOOLEAN_FIELDS = {"intent_mismatch"}
KNOWN_FIELDS = TEXT_FIELDS | LIST_TEXT_FIELDS | NUMERIC_FIELDS | BOOLEAN_FIELDS

SECRET_VALUE_PATTERNS = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{8,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bASIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-+/=]{10,}\b", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
    re.compile(r"\b(?:env|secret_ref|vault):[A-Za-z0-9_./:-]+\b", re.IGNORECASE),
)


class PolicyPackValidationError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PolicyPackDocument:
    pack_name: str
    pack_version: str
    description: str
    recommended_scope: tuple[str, ...]
    policies: tuple[dict[str, Any], ...]
    source_path: Path


def read_policy_pack(path: str | Path | None = None) -> PolicyPackDocument:
    source_path = Path(path) if path else DEFAULT_POLICY_PACK_PATH
    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PolicyPackValidationError(f"Policy pack file not found: {source_path}") from exc
    except json.JSONDecodeError as exc:
        raise PolicyPackValidationError(f"Policy pack file is not valid JSON: {source_path}: {exc}") from exc
    return validate_policy_pack_payload(raw, source_path=source_path)


def validate_policy_pack_payload(
    payload: dict[str, Any],
    *,
    source_path: str | Path = "<memory>",
) -> PolicyPackDocument:
    if not isinstance(payload, dict):
        raise PolicyPackValidationError("Policy pack payload must be a JSON object.")

    allowed_top_level = {"pack_name", "pack_version", "description", "recommended_scope", "policies"}
    unknown_top_level = sorted(set(payload.keys()) - allowed_top_level)
    if unknown_top_level:
        raise PolicyPackValidationError(
            f"Policy pack contains unsupported top-level fields: {', '.join(unknown_top_level)}"
        )

    pack_name = _require_non_empty_string(payload.get("pack_name"), "pack_name")
    pack_version = _require_non_empty_string(payload.get("pack_version"), "pack_version")
    description = _require_non_empty_string(payload.get("description"), "description")
    recommended_scope = payload.get("recommended_scope") or []
    if not isinstance(recommended_scope, list) or any(not isinstance(item, str) or not item.strip() for item in recommended_scope):
        raise PolicyPackValidationError("recommended_scope must be a list of non-empty strings when present.")

    policies = payload.get("policies")
    if not isinstance(policies, list) or not policies:
        raise PolicyPackValidationError("policies must be a non-empty list.")

    normalized_policies: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, policy in enumerate(policies):
        normalized = validate_policy_definition(
            policy,
            policy_index=index,
            pack_name=pack_name,
        )
        lowered_name = normalized["name"].strip().lower()
        if lowered_name in seen_names:
            raise PolicyPackValidationError(f"Duplicate policy name found: {normalized['name']}")
        seen_names.add(lowered_name)
        normalized_policies.append(normalized)

    findings = find_secret_like_values(payload)
    if findings:
        formatted = "; ".join(findings[:5])
        raise PolicyPackValidationError(f"Policy pack contains secret-like values or secret references: {formatted}")

    return PolicyPackDocument(
        pack_name=pack_name,
        pack_version=pack_version,
        description=description,
        recommended_scope=tuple(item.strip() for item in recommended_scope),
        policies=tuple(normalized_policies),
        source_path=Path(source_path),
    )


def validate_policy_definition(
    policy: dict[str, Any],
    *,
    policy_index: int,
    pack_name: str,
) -> dict[str, Any]:
    if not isinstance(policy, dict):
        raise PolicyPackValidationError(f"Policy at index {policy_index} must be an object.")

    unknown_policy_fields = sorted(set(policy.keys()) - ALLOWED_POLICY_FIELDS)
    if unknown_policy_fields:
        raise PolicyPackValidationError(
            f"Policy '{policy.get('name', f'#{policy_index}')}' contains unsupported fields: "
            f"{', '.join(unknown_policy_fields)}"
        )

    missing_fields = [field for field in ALLOWED_POLICY_FIELDS if field not in policy]
    if missing_fields:
        raise PolicyPackValidationError(
            f"Policy '{policy.get('name', f'#{policy_index}')}' is missing required fields: {', '.join(sorted(missing_fields))}"
        )

    name = _require_non_empty_string(policy.get("name"), f"policies[{policy_index}].name")
    description = _require_non_empty_string(policy.get("description"), f"policies[{policy_index}].description")
    enabled = policy.get("enabled")
    if not isinstance(enabled, bool):
        raise PolicyPackValidationError(f"Policy '{name}' must set enabled to true or false.")

    severity = _normalize_choice(
        policy.get("severity"),
        field_name=f"Policy '{name}' severity",
        allowed_values=ALLOWED_SEVERITIES,
    )
    decision = _normalize_choice(
        policy.get("decision"),
        field_name=f"Policy '{name}' decision",
        allowed_values=ALLOWED_DECISIONS,
    )

    conditions = policy.get("conditions")
    normalized_conditions = validate_conditions(conditions, policy_name=name)

    if pack_name == "pilot-default":
        if not enabled:
            raise PolicyPackValidationError(f"Pilot default policy '{name}' must stay enabled.")
        if severity not in {"high", "critical"}:
            raise PolicyPackValidationError(
                f"Pilot default policy '{name}' must use severity high or critical."
            )
        if decision not in {"block", "require_approval"}:
            raise PolicyPackValidationError(
                f"Pilot default policy '{name}' must use decision block or require_approval."
            )

    return {
        "name": name,
        "description": description,
        "enabled": enabled,
        "severity": severity,
        "decision": decision,
        "conditions": normalized_conditions,
    }


def validate_conditions(conditions: Any, *, policy_name: str) -> dict[str, Any]:
    if not isinstance(conditions, dict):
        raise PolicyPackValidationError(f"Policy '{policy_name}' conditions must be an object.")

    unknown_condition_fields = sorted(set(conditions.keys()) - ALLOWED_CONDITION_FIELDS)
    if unknown_condition_fields:
        raise PolicyPackValidationError(
            f"Policy '{policy_name}' conditions contain unsupported fields: {', '.join(unknown_condition_fields)}"
        )

    match = _normalize_choice(
        conditions.get("match"),
        field_name=f"Policy '{policy_name}' conditions.match",
        allowed_values=ALLOWED_MATCH_VALUES,
    )
    rules = conditions.get("rules")
    if not isinstance(rules, list) or not rules:
        raise PolicyPackValidationError(f"Policy '{policy_name}' conditions.rules must be a non-empty list.")

    normalized_rules: list[dict[str, Any]] = []
    for index, rule in enumerate(rules):
        normalized_rules.append(validate_rule(rule, policy_name=policy_name, rule_index=index))

    return {"match": match, "rules": normalized_rules}


def validate_rule(rule: Any, *, policy_name: str, rule_index: int) -> dict[str, Any]:
    if not isinstance(rule, dict):
        raise PolicyPackValidationError(f"Policy '{policy_name}' rule {rule_index} must be an object.")

    unknown_rule_fields = sorted(set(rule.keys()) - ALLOWED_RULE_FIELDS)
    if unknown_rule_fields:
        raise PolicyPackValidationError(
            f"Policy '{policy_name}' rule {rule_index} contains unsupported fields: {', '.join(unknown_rule_fields)}"
        )

    field_name = _normalize_choice(
        rule.get("field"),
        field_name=f"Policy '{policy_name}' rule {rule_index} field",
        allowed_values=KNOWN_FIELDS,
    )
    operator = _normalize_choice(
        rule.get("operator"),
        field_name=f"Policy '{policy_name}' rule {rule_index} operator",
        allowed_values=ALLOWED_OPERATORS,
    )
    value = rule.get("value")

    if field_name in NUMERIC_FIELDS:
        if operator not in {"equals", "greater_than"}:
            raise PolicyPackValidationError(
                f"Policy '{policy_name}' rule {rule_index} uses unsupported operator '{operator}' for numeric field '{field_name}'."
            )
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise PolicyPackValidationError(
                f"Policy '{policy_name}' rule {rule_index} requires a numeric value for '{field_name}'."
            )
    elif field_name in BOOLEAN_FIELDS:
        if operator != "equals" or not isinstance(value, bool):
            raise PolicyPackValidationError(
                f"Policy '{policy_name}' rule {rule_index} requires boolean equality for '{field_name}'."
            )
    elif field_name in LIST_TEXT_FIELDS:
        if operator != "contains" or not isinstance(value, str) or not value.strip():
            raise PolicyPackValidationError(
                f"Policy '{policy_name}' rule {rule_index} requires a non-empty string with operator 'contains' for '{field_name}'."
            )
        value = value.strip()
    else:
        if operator == "greater_than":
            raise PolicyPackValidationError(
                f"Policy '{policy_name}' rule {rule_index} uses numeric comparison on non-numeric field '{field_name}'."
            )
        if not isinstance(value, str) or not value.strip():
            raise PolicyPackValidationError(
                f"Policy '{policy_name}' rule {rule_index} requires a non-empty string value for '{field_name}'."
            )
        value = value.strip()

    return {"field": field_name, "operator": operator, "value": value}


def canonicalize_policy(policy: dict[str, Any]) -> dict[str, Any]:
    canonical = {
        "name": _normalize_whitespace(str(policy.get("name", ""))),
        "description": _normalize_whitespace(str(policy.get("description", ""))),
        "enabled": bool(policy.get("enabled")),
        "severity": str(policy.get("severity", "")).strip().lower(),
        "decision": str(policy.get("decision", "")).strip().lower(),
        "conditions": {
            "match": str(((policy.get("conditions") or {}).get("match") or "")).strip().lower(),
            "rules": [],
        },
    }

    rules = ((policy.get("conditions") or {}).get("rules") or [])
    for rule in rules:
        value = rule.get("value")
        if isinstance(value, str):
            value = value.strip().lower()
        canonical["conditions"]["rules"].append(
            {
                "field": str(rule.get("field", "")).strip().lower(),
                "operator": str(rule.get("operator", "")).strip().lower(),
                "value": value,
            }
        )
    return canonical


def policy_signature(policy: dict[str, Any]) -> str:
    return json.dumps(canonicalize_policy(policy), sort_keys=True, separators=(",", ":"))


def extract_policy_payload(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": record.get("name"),
        "description": record.get("description"),
        "enabled": record.get("enabled"),
        "severity": record.get("severity"),
        "decision": record.get("decision"),
        "conditions": record.get("conditions"),
    }


def find_secret_like_values(node: Any, *, path: str = "root") -> list[str]:
    findings: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            findings.extend(find_secret_like_values(value, path=f"{path}.{key}"))
        return findings
    if isinstance(node, list):
        for index, item in enumerate(node):
            findings.extend(find_secret_like_values(item, path=f"{path}[{index}]"))
        return findings
    if isinstance(node, str):
        if any(pattern.search(node) for pattern in SECRET_VALUE_PATTERNS):
            findings.append(path)
    return findings


def _require_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyPackValidationError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _normalize_choice(value: Any, *, field_name: str, allowed_values: set[str]) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyPackValidationError(f"{field_name} must be a non-empty string.")
    normalized = value.strip().lower()
    if normalized not in allowed_values:
        raise PolicyPackValidationError(
            f"{field_name} must be one of: {', '.join(sorted(allowed_values))}."
        )
    return normalized


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())
