from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]


def test_security_review_docs_are_linked_from_readme_and_root_security_policy():
    expected_links = [
        "[Threat Model](docs/security/THREAT_MODEL.md)",
        "[Security Review Checklist](docs/security/SECURITY_REVIEW_CHECKLIST.md)",
        "[Incident Response](docs/security/INCIDENT_RESPONSE.md)",
        "[Audit Integrity](docs/security/audit-integrity.md)",
    ]
    readme_text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    root_security_text = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")

    for relative_path in (
        "docs/security/THREAT_MODEL.md",
        "docs/security/SECURITY_REVIEW_CHECKLIST.md",
        "docs/security/INCIDENT_RESPONSE.md",
        "docs/security/audit-integrity.md",
    ):
        assert (REPO_ROOT / relative_path).exists()

    for link in expected_links:
        assert link in readme_text
        assert link in root_security_text


def test_public_repo_secret_placeholder_check_passes():
    script_path = REPO_ROOT / "scripts" / "check-no-live-secrets.py"

    completed = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
