from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from apply_policy_pack import ApplyReport, PlanItem, PolicyPackApplier  # noqa: E402
from policy_pack_utils import (  # noqa: E402
    DEFAULT_POLICY_PACK_PATH,
    PolicyPackValidationError,
    extract_policy_payload,
    policy_signature,
    read_policy_pack,
    validate_policy_pack_payload,
)


class FakePolicyClient:
    def __init__(self, existing: list[dict] | None = None) -> None:
        self.records = [copy.deepcopy(item) for item in (existing or [])]
        self.created_payloads: list[dict] = []
        self.updated_payloads: list[tuple[str, dict]] = []

    def list_policies(self) -> list[dict]:
        return [copy.deepcopy(item) for item in self.records]

    def create_policy(self, payload: dict) -> dict:
        record = {"id": f"created-{len(self.records) + 1}", **copy.deepcopy(payload)}
        self.records.append(record)
        self.created_payloads.append(copy.deepcopy(payload))
        return copy.deepcopy(record)

    def update_policy(self, policy_id: str, payload: dict) -> dict:
        for index, record in enumerate(self.records):
            if record["id"] == policy_id:
                updated = {"id": policy_id, **copy.deepcopy(payload)}
                self.records[index] = updated
                self.updated_payloads.append((policy_id, copy.deepcopy(payload)))
                return copy.deepcopy(updated)
        raise AssertionError(f"Unknown policy id {policy_id}")


def test_repo_policy_pack_validates():
    document = read_policy_pack(DEFAULT_POLICY_PACK_PATH)

    assert document.pack_name == "pilot-default"
    assert len(document.policies) >= 10
    assert any(policy["name"] == "Require approval for external MCP tools" for policy in document.policies)


def test_repo_policy_pack_contains_no_secret_like_values():
    document = read_policy_pack(DEFAULT_POLICY_PACK_PATH)

    serialized = str(document)
    assert "env:" not in serialized.lower()
    assert "secret_ref:" not in serialized.lower()
    assert "bearer " not in serialized.lower()


def test_policy_pack_rejects_invalid_numeric_operator_field():
    with pytest.raises(PolicyPackValidationError):
        validate_policy_pack_payload(
            {
                "pack_name": "pilot-default",
                "pack_version": "test",
                "description": "invalid",
                "policies": [
                    {
                        "name": "Invalid threshold policy",
                        "description": "Should fail validation",
                        "enabled": True,
                        "severity": "high",
                        "decision": "require_approval",
                        "conditions": {
                            "match": "all",
                            "rules": [
                                {"field": "tool_name", "operator": "greater_than", "value": 10},
                            ],
                        },
                    }
                ],
            }
        )


def test_policy_pack_rejects_secret_like_value():
    with pytest.raises(PolicyPackValidationError):
        validate_policy_pack_payload(
            {
                "pack_name": "pilot-default",
                "pack_version": "test",
                "description": "invalid",
                "policies": [
                    {
                        "name": "Unsafe value policy",
                        "description": "Should fail validation",
                        "enabled": True,
                        "severity": "high",
                        "decision": "require_approval",
                        "conditions": {
                            "match": "all",
                            "rules": [
                                {"field": "tool_name", "operator": "equals", "value": "env:AGENTGATE_GITHUB_TOKEN"},
                            ],
                        },
                    }
                ],
            }
        )


def test_apply_policy_pack_dry_run_does_not_mutate():
    document = read_policy_pack(DEFAULT_POLICY_PACK_PATH)
    client = FakePolicyClient(existing=[])
    applier = PolicyPackApplier(client)

    plan = applier.build_plan(document, update_existing=False)
    report = applier.apply_plan(plan[:2], dry_run=True)

    assert isinstance(report, ApplyReport)
    assert report.created == 0
    assert report.updated == 0
    assert client.created_payloads == []
    assert client.updated_payloads == []
    assert len(client.records) == 0


def test_apply_policy_pack_is_idempotent_for_matching_policy():
    document = read_policy_pack(DEFAULT_POLICY_PACK_PATH)
    existing = {"id": "policy-1", **copy.deepcopy(document.policies[0])}
    client = FakePolicyClient(existing=[existing])
    applier = PolicyPackApplier(client)

    plan = applier.build_plan(document, update_existing=False)

    first_item = plan[0]
    assert first_item.action == "skip"
    assert client.created_payloads == []
    assert client.updated_payloads == []
    assert policy_signature(extract_policy_payload(existing)) == policy_signature(document.policies[0])


def test_apply_policy_pack_updates_only_when_explicitly_requested():
    document = read_policy_pack(DEFAULT_POLICY_PACK_PATH)
    conflicting = {"id": "policy-1", **copy.deepcopy(document.policies[0])}
    conflicting["description"] = "Local custom description"
    client = FakePolicyClient(existing=[conflicting])
    applier = PolicyPackApplier(client)

    conflict_plan = applier.build_plan(document, update_existing=False)
    assert conflict_plan[0].action == "conflict"

    update_plan = applier.build_plan(document, update_existing=True)
    assert update_plan[0].action == "update"
    report = applier.apply_plan(update_plan[:1], dry_run=False)

    assert report.updated == 1
    assert client.updated_payloads[0][0] == "policy-1"
