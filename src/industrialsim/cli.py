from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable, Sequence

from industrialsim.application import (
    inspect_checkpoint,
    resume_episode,
    run_episode,
    validate_config,
)


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

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect a simulation checkpoint file",
    )
    inspect_parser.add_argument(
        "checkpoint_path",
        help="Path to the checkpoint file",
    )

    resume_parser = subparsers.add_parser(
        "resume",
        help="Resume an episode from a simulation checkpoint file",
    )
    resume_parser.add_argument(
        "checkpoint_path",
        help="Path to the checkpoint file",
    )
    resume_parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Optional path to the YAML configuration file to validate against checkpoint",
    )

    return parser


def _execute_cli_action(action: Any) -> int:
    try:
        result = action()
        print(json.dumps(result.to_dict(), indent=2))
        return 0
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}, indent=2))
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.command == "validate":
        result = validate_config(args.config_path)
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.is_valid else 1

    if args.command == "run":
        return _execute_cli_action(lambda: run_episode(args.config_path))

    if args.command == "inspect":
        return _execute_cli_action(lambda: inspect_checkpoint(args.checkpoint_path))

    if args.command == "resume":
        return _execute_cli_action(lambda: resume_episode(args.checkpoint_path, config_source=args.config_path))

    return 1


if __name__ == "__main__":
    sys.exit(main())
