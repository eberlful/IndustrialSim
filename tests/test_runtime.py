import sys
import pytest
from industrialsim import check_runtime, enforce_cpython_312


def test_runtime_allows_cpython_312() -> None:
    # Under test environment (Python 3.12.x CPython), check_runtime must succeed
    assert sys.version_info[:2] == (3, 12)
    assert sys.implementation.name == "cpython"
    check_runtime()


def test_runtime_rejects_other_versions() -> None:
    with pytest.raises(RuntimeError, match="IndustrialSim requires CPython 3.12"):
        enforce_cpython_312(impl_name="cpython", version_info=(3, 14, 0))

    with pytest.raises(RuntimeError, match="IndustrialSim requires CPython 3.12"):
        enforce_cpython_312(impl_name="cpython", version_info=(3, 15, 0))

    with pytest.raises(RuntimeError, match="IndustrialSim requires CPython 3.12"):
        enforce_cpython_312(impl_name="pypy", version_info=(3, 12, 0))
