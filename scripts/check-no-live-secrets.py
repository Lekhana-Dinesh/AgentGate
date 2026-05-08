from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

PATTERNS = {
    "github_pat_classic": re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    "github_pat_fine_grained": re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    "slack_bot_token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
}

ALLOWED_LITERALS = {
    "ghp_your_token_here",
    "xoxb-your-bot-token",
}


def iter_target_files() -> list[Path]:
    candidates = {
        REPO_ROOT / "README.md",
        REPO_ROOT / "SECURITY.md",
        REPO_ROOT / "CONTRIBUTING.md",
        REPO_ROOT / ".env.example",
        REPO_ROOT / "docker-compose.yml",
    }
    candidates.update((REPO_ROOT / "docs").rglob("*.md"))
    candidates.update((REPO_ROOT / ".github").rglob("*.md"))
    candidates.update((REPO_ROOT / ".github").rglob("*.yml"))
    return sorted(path for path in candidates if path.is_file())


def main() -> int:
    violations: list[str] = []

    for path in iter_target_files():
        relative_path = path.relative_to(REPO_ROOT)
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for pattern_name, pattern in PATTERNS.items():
                for match in pattern.finditer(line):
                    token = match.group(0)
                    if token in ALLOWED_LITERALS:
                        continue
                    violations.append(
                        f"{relative_path}:{line_number}: {pattern_name}: {token}"
                    )

    if violations:
        print("Potential live secret patterns found in public docs or config surfaces:")
        for violation in violations:
            print(violation)
        return 1

    print("No live secret patterns found in public docs or config surfaces.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
