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


def test_cli_branch_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from test_branch_counterfactual_decisions_e2e import BASE_DECISION_YAML
    from industrialsim.application import create_checkpoint, save_checkpoint

    cp = create_checkpoint(BASE_DECISION_YAML, pause_at_decision_batch=True)
    cp_file = tmp_path / "decision_cp.json"
    save_checkpoint(cp, cp_file)

    act1_file = tmp_path / "actions1.json"
    act1_file.write_text(
        json.dumps([{"action_type": "buffer_reorder", "target_id": "buf-1", "new_order": ["u-1", "u-2"]}]),
        encoding="utf-8",
    )

    act2_file = tmp_path / "actions2.json"
    act2_file.write_text(
        json.dumps([{"action_type": "buffer_reorder", "target_id": "buf-1", "new_order": ["u-2", "u-1"]}]),
        encoding="utf-8",
    )

    exit_code = main(["branch", str(cp_file), str(act1_file), str(act2_file)])
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "branches" in data
    assert len(data["branches"]) == 2
    assert "branch_id" in data["branches"][0]
    assert "raw_metrics" in data["branches"][0]
    assert "hard_constraints" in data["branches"][0]


def test_cli_branch_failure_fewer_than_two_alternatives(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from test_branch_counterfactual_decisions_e2e import BASE_DECISION_YAML
    from industrialsim.application import create_checkpoint, save_checkpoint

    cp = create_checkpoint(BASE_DECISION_YAML, pause_at_decision_batch=True)
    cp_file = tmp_path / "decision_cp.json"
    save_checkpoint(cp, cp_file)

    act1_file = tmp_path / "actions1.json"
    act1_file.write_text(
        json.dumps([{"action_type": "buffer_reorder", "target_id": "buf-1", "new_order": ["u-1", "u-2"]}]),
        encoding="utf-8",
    )

    exit_code = main(["branch", str(cp_file), str(act1_file)])
    assert exit_code == 1

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "between 2 and 8" in data["error"].lower()


def test_cli_branch_three_alternatives(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from test_branch_counterfactual_decisions_e2e import BASE_DECISION_YAML
    from industrialsim.application import create_checkpoint, save_checkpoint

    cp = create_checkpoint(BASE_DECISION_YAML, pause_at_decision_batch=True)
    cp_file = tmp_path / "decision_cp.json"
    save_checkpoint(cp, cp_file)

    act1_file = tmp_path / "actions1.json"
    act1_file.write_text(
        json.dumps([{"action_type": "buffer_reorder", "target_id": "buf-1", "new_order": ["u-1", "u-2"]}]),
        encoding="utf-8",
    )

    act2_file = tmp_path / "actions2.json"
    act2_file.write_text(
        json.dumps([{"action_type": "buffer_reorder", "target_id": "buf-1", "new_order": ["u-2", "u-1"]}]),
        encoding="utf-8",
    )

    act3_file = tmp_path / "actions3.json"
    act3_file.write_text(
        json.dumps([{"action_type": "buffer_reorder", "target_id": "buf-1", "new_order": ["u-1", "u-2"]}]),
        encoding="utf-8",
    )

    exit_code = main(["branch", str(cp_file), str(act1_file), str(act2_file), str(act3_file)])
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert len(data["branches"]) == 3


def test_cli_branch_with_workers(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from test_branch_counterfactual_decisions_e2e import BASE_DECISION_YAML
    from industrialsim.application import create_checkpoint, save_checkpoint

    cp = create_checkpoint(BASE_DECISION_YAML, pause_at_decision_batch=True)
    cp_file = tmp_path / "decision_cp.json"
    save_checkpoint(cp, cp_file)

    act1_file = tmp_path / "actions1.json"
    act1_file.write_text(
        json.dumps([{"action_type": "buffer_reorder", "target_id": "buf-1", "new_order": ["u-1", "u-2"]}]),
        encoding="utf-8",
    )

    act2_file = tmp_path / "actions2.json"
    act2_file.write_text(
        json.dumps([{"action_type": "buffer_reorder", "target_id": "buf-1", "new_order": ["u-2", "u-1"]}]),
        encoding="utf-8",
    )

    exit_code = main(["branch", str(cp_file), str(act1_file), str(act2_file), "--workers", "2"])
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "branches" in data
    assert len(data["branches"]) == 2
    assert data["branches"][0]["status"] == "completed"


def test_cli_benchmark_scheduler(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["benchmark", "--target", "scheduler", "--scheduler-events", "1000", "--repetitions", "2"])
    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "passed"
    assert "scheduler" in data
    assert data["scheduler"] is not None
    assert "timing" in data["scheduler"]
    assert "hardware" in data
    assert "runtime" in data


def test_cli_benchmark_with_output_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out_dir = tmp_path / "bench_report"
    exit_code = main([
        "benchmark",
        "--target", "scheduler",
        "--scheduler-events", "1000",
        "--output-dir", str(out_dir),
    ])
    assert exit_code == 0
    report_file = out_dir / "benchmark_report.json"
    assert report_file.exists()
    data = json.loads(report_file.read_text(encoding="utf-8"))
    assert data["status"] == "passed"






