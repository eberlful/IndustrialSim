from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from industrialsim.application import run_episode, validate_config


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="industrialsim",
        description="Industrial Production Simulation CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate a YAML simulation configuration file",
    )
    validate_parser.add_argument(
        "config_path",
        help="Path to the YAML configuration file",
    )

    run_parser = subparsers.add_parser(
        "run",
        help="Run an episode defined by a YAML configuration file",
    )
    run_parser.add_argument(
        "config_path",
        help="Path to the YAML configuration file",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.command == "validate":
        result = validate_config(args.config_path)
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.is_valid else 1

    if args.command == "run":
        try:
            summary = run_episode(args.config_path)
            print(json.dumps(summary.to_dict(), indent=2))
            return 0
        except Exception as e:
            print(json.dumps({"status": "error", "error": str(e)}, indent=2))
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
