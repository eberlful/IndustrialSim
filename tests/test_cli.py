import json
from pathlib import Path
import pytest
from industrialsim.cli import main


MINIMAL_VALID_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"
production_units:
  - id: "unit-001"
    variant: "sedan"
    release_time: "0s"
stations:
  - id: "station-001"
    operations:
      - id: "op-assembly"
        duration: "10s"
"""

INVALID_YAML = """
schema_version: "1.0"
seed: 42
unknown_property: "boom"
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"
production_units:
  - id: "unit-001"
    variant: "sedan"
stations:
  - id: "station-001"
    operations:
      - id: "op-assembly"
        duration: "10s"
"""


def test_cli_validate_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(MINIMAL_VALID_YAML, encoding="utf-8")

    exit_code = main(["validate", str(cfg_file)])
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["valid"] is True
    assert data["errors"] == []


def test_cli_validate_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg_file = tmp_path / "invalid.yaml"
    cfg_file.write_text(INVALID_YAML, encoding="utf-8")

    exit_code = main(["validate", str(cfg_file)])
    assert exit_code == 1

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["valid"] is False
    assert len(data["errors"]) > 0


def test_cli_run_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(MINIMAL_VALID_YAML, encoding="utf-8")

    exit_code = main(["run", str(cfg_file)])
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "completed"
    assert data["simulated_time_ns"] == 10_000_000_000
    assert "result_hash" in data


def test_cli_run_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg_file = tmp_path / "invalid.yaml"
    cfg_file.write_text(INVALID_YAML, encoding="utf-8")

    exit_code = main(["run", str(cfg_file)])
    assert exit_code == 1

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "error"
    assert "error" in data
