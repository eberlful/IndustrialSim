from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable, Sequence

from industrialsim.application import (
    branch_checkpoint,
    inspect,
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
    run_parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default=None,
        help="Optional path to directory where run artifacts should be written",
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect a simulation checkpoint file or run artifact directory",
    )
    inspect_parser.add_argument(
        "path",
        help="Path to the checkpoint file or run artifact directory",
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

    branch_parser = subparsers.add_parser(
        "branch",
        help="Branch counterfactual decisions from a simulation checkpoint",
    )
    branch_parser.add_argument(
        "checkpoint_path",
        help="Path to the Decision Checkpoint file",
    )
    branch_parser.add_argument(
        "action_files",
        nargs="+",
        help="Paths to at least two JSON files containing alternative Action sets",
    )
    branch_parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Optional path to the YAML configuration file to validate against checkpoint",
    )
    branch_parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default=None,
        help="Optional path to directory where branch artifacts should be written",
    )
    branch_parser.add_argument(
        "--workers",
        dest="workers",
        type=int,
        default=1,
        help="Number of worker processes for parallel branch execution (default: 1)",
    )

    benchmark_parser = subparsers.add_parser(
        "benchmark",
        help="Run scheduler or reference plant benchmarks",
    )
    benchmark_parser.add_argument(
        "--target",
        dest="target",
        choices=["all", "scheduler", "plant", "reference_plant"],
        default="all",
        help="Benchmark target to execute (default: all)",
    )
    benchmark_parser.add_argument(
        "--scheduler-events",
        "--events",
        dest="scheduler_events",
        type=int,
        default=5_000_000,
        help="Number of simple events for Scheduler benchmark (default: 5,000,000)",
    )
    benchmark_parser.add_argument(
        "--plant-events",
        dest="plant_events",
        type=int,
        default=100_000,
        help="Target events for Reference Plant benchmark (default: 100,000)",
    )
    benchmark_parser.add_argument(
        "--repetitions",
        dest="repetitions",
        type=int,
        default=2,
        help="Number of repetitions to verify determinism (default: 2)",
    )
    benchmark_parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default=None,
        help="Optional path to directory where benchmark report should be written",
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
        return _execute_cli_action(lambda: run_episode(args.config_path, output_dir=args.output_dir))

    if args.command == "inspect":
        return _execute_cli_action(lambda: inspect(args.path))

    if args.command == "resume":
        return _execute_cli_action(lambda: resume_episode(args.checkpoint_path, config_source=args.config_path))

    if args.command == "branch":
        def run_branch() -> Any:
            if len(args.action_files) < 2:
                raise ValueError(
                    f"Counterfactual branching requires at least two alternative Action sets, got {len(args.action_files)}"
                )
            from pathlib import Path

            alternatives: list[Any] = []
            for file_str in args.action_files:
                p = Path(file_str)
                data = json.loads(p.read_text(encoding="utf-8"))
                alternatives.append(data)

            return branch_checkpoint(
                args.checkpoint_path,
                alternative_actions=alternatives,
                config_source=args.config_path,
                output_dir=args.output_dir,
                workers=args.workers,
            )

        return _execute_cli_action(run_branch)

    if args.command == "benchmark":
        from industrialsim.benchmark import run_benchmark

        return _execute_cli_action(
            lambda: run_benchmark(
                target=args.target,
                scheduler_events=args.scheduler_events,
                plant_events=args.plant_events,
                repetitions=args.repetitions,
                output_dir=args.output_dir,
            )
        )

    return 1


if __name__ == "__main__":
    sys.exit(main())

