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


def test_cli_material_flow_run_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from test_material_flow_simulation import BLOCKING_SCENARIO_YAML

    cfg_file = tmp_path / "mf_scenario.yaml"
    cfg_file.write_text(BLOCKING_SCENARIO_YAML, encoding="utf-8")

    exit_code = main(["run", str(cfg_file)])
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "completed"
    assert len(data["production_units"]) == 3
    assert len(data["buffers"]) == 1
    assert data["buffers"][0]["id"] == "buf-1"
    st1 = next(s for s in data["stations"] if s["id"] == "st-1")
    assert st1["total_blocked_time_ns"] == 6_000_000_000


def test_cli_inspect_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from industrialsim.application import create_checkpoint, save_checkpoint

    cp = create_checkpoint(MINIMAL_VALID_YAML, at_time_ns=5_000_000_000)
    cp_file = tmp_path / "cp.json"
    save_checkpoint(cp, cp_file)

    exit_code = main(["inspect", str(cp_file)])
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["schema_version"] == "1.0"
    assert data["kernel_version"] == "1.0"
    assert data["simulated_time_ns"] == 5_000_000_000
    assert "config_hash" in data
    assert "model_hash" in data
    assert "queue_size" in data


def test_cli_inspect_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    non_existent = tmp_path / "does_not_exist.json"

    exit_code = main(["inspect", str(non_existent)])
    assert exit_code == 1

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "error"
    assert "error" in data


def test_cli_resume_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from industrialsim.application import create_checkpoint, save_checkpoint

    cp = create_checkpoint(MINIMAL_VALID_YAML, at_time_ns=5_000_000_000)
    cp_file = tmp_path / "cp.json"
    save_checkpoint(cp, cp_file)

    exit_code = main(["resume", str(cp_file)])
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "completed"
    assert data["simulated_time_ns"] == 10_000_000_000
    assert "result_hash" in data


def test_cli_resume_with_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from industrialsim.application import create_checkpoint, save_checkpoint

    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(MINIMAL_VALID_YAML, encoding="utf-8")

    cp = create_checkpoint(MINIMAL_VALID_YAML, at_time_ns=5_000_000_000)
    cp_file = tmp_path / "cp.json"
    save_checkpoint(cp, cp_file)

    exit_code = main(["resume", str(cp_file), "--config", str(cfg_file)])
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "completed"


def test_cli_resume_failure_incompatible_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from industrialsim.application import create_checkpoint, save_checkpoint

    incompat_yaml = MINIMAL_VALID_YAML.replace("duration: \"10s\"", "duration: \"30s\"")
    incompat_file = tmp_path / "incompat.yaml"
    incompat_file.write_text(incompat_yaml, encoding="utf-8")

    cp = create_checkpoint(MINIMAL_VALID_YAML, at_time_ns=5_000_000_000)
    cp_file = tmp_path / "cp.json"
    save_checkpoint(cp, cp_file)

    exit_code = main(["resume", str(cp_file), "--config", str(incompat_file)])
    assert exit_code == 1

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "error"
    assert "mismatch" in data["error"].lower()


