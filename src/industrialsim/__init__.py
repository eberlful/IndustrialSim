import sys
from typing import Any, Sequence


def enforce_cpython_312(impl_name: str, version_info: Sequence[Any] | tuple[Any, ...]) -> None:
    if tuple(version_info[:2]) != (3, 12) or impl_name != "cpython":
        version_str = ".".join(str(v) for v in version_info[:3])
        raise RuntimeError(
            f"IndustrialSim requires CPython 3.12 (minor release 3.12.x), got {impl_name} {version_str}"
        )


def check_runtime() -> None:
    enforce_cpython_312(
        impl_name=sys.implementation.name,
        version_info=sys.version_info,
    )


# Enforce runtime constraint when industrialsim is loaded
check_runtime()


def main() -> int:
    from industrialsim.cli import main as cli_main

    return cli_main()
