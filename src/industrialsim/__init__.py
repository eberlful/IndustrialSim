import sys
from typing import Any, Sequence


def enforce_cpython_314(impl_name: str, version_info: Sequence[Any] | tuple[Any, ...]) -> None:
    if tuple(version_info[:2]) != (3, 14) or impl_name != "cpython":
        version_str = ".".join(str(v) for v in version_info[:3])
        raise RuntimeError(
            f"IndustrialSim requires CPython 3.14 (minor release 3.14.x), got {impl_name} {version_str}"
        )


def check_runtime() -> None:
    enforce_cpython_314(
        impl_name=sys.implementation.name,
        version_info=sys.version_info,
    )


# Enforce runtime constraint when industrialsim is loaded
check_runtime()


def main() -> None:
    from industrialsim.cli import main as cli_main

    cli_main()
