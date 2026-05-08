from __future__ import annotations

import argparse
import sys

from policy_pack_utils import (
    DEFAULT_POLICY_PACK_PATH,
    PolicyPackValidationError,
    read_policy_pack,
)


EXIT_SUCCESS = 0
EXIT_VALIDATION_FAILED = 1
EXIT_CONFIG_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description="Validate an AgentGate policy-pack JSON file for structure, safe values, and obvious pilot-safety issues.",
        epilog="Exit codes: 0=success, 1=validation failed, 2=invalid CLI configuration.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.add_argument(
        "--pack",
        default=str(DEFAULT_POLICY_PACK_PATH),
        help="Path to the policy-pack JSON file.",
    )
    args = parser.parse_args(argv or sys.argv[1:])

    try:
        document = read_policy_pack(args.pack)
    except PolicyPackValidationError as exc:
        print(f"[fail] Validation: {exc}", file=sys.stderr)
        return EXIT_VALIDATION_FAILED
    except Exception as exc:
        print(f"[fail] Configuration: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    print(
        f"[ok] Policy pack '{document.pack_name}' version {document.pack_version} is valid "
        f"({len(document.policies)} policies)."
    )
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
