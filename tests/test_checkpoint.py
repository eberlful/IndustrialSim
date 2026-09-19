import json
from pathlib import Path
import pytest
from industrialsim.checkpoint import (
    Checkpoint,
    CheckpointInspection,
    save_checkpoint,
    load_checkpoint,
    serialize_checkpoint,
    deserialize_checkpoint,
    inspect_checkpoint,
    InvalidCheckpointError,
)


def sample_checkpoint() -> Checkpoint:
    return Checkpoint(
        schema_version="1.0",
        kernel_version="1.0",
        model_hash="abc123model",
        config_hash="def456config",
        simulated_time_ns=5_000_000_000,
        sequence_counter=42,
        events_processed=10,
        event_queue=[
            {
                "time_ns": 6_000_000_000,
                "priority": 30,
                "sequence": 43,
                "event_type": "COMPLETE_OPERATION",
                "payload_version": 1,
                "payload": {"unit_id": "u1", "station_id": "st1"},
            }
        ],
        domain_state={
            "production_units": {
                "u1": {
                    "id": "u1",
                    "variant": "sedan",
                    "quality_state": "nominal",
                    "state": "in_station",
                    "location": "st1",
                    "history": [],
                }
            },
            "stations": {
                "st1": {
                    "id": "st1",
                    "operations_completed": 0,
                    "total_busy_time_ns": 0,
                    "total_blocked_time_ns": 0,
                    "is_busy": True,
                    "is_blocked": False,
                    "current_unit_id": "u1",
                    "blocked_unit_id": None,
                    "output_buffer": [],
                    "busy_start_ns": 5_000_000_000,
                    "blocked_start_ns": None,
                }
            },
            "buffers": {},
            "in_flight_to": {"st1": 0},
            "source_pending_units": {},
        },
        root_seed=42,
        random_occurrence_counters={"arrival_stream": 5},
        plugin_metadata={},
        configuration={"schema_version": "1.0", "seed": 42},
    )


def test_checkpoint_serialize_and_deserialize() -> None:
    cp = sample_checkpoint()
    serialized = serialize_checkpoint(cp)
    assert isinstance(serialized, str)

    loaded = deserialize_checkpoint(serialized)
    assert loaded.schema_version == cp.schema_version
    assert loaded.kernel_version == cp.kernel_version
    assert loaded.model_hash == cp.model_hash
    assert loaded.config_hash == cp.config_hash
    assert loaded.simulated_time_ns == 5_000_000_000
    assert loaded.next_sequence == 42
    assert loaded.sequence_counter == 42
    assert loaded.events_processed == 10
    assert loaded.root_seed == 42
    assert loaded.random_occurrence_counters == {"arrival_stream": 5}
    assert len(loaded.event_queue) == 1
    assert loaded.event_queue[0]["event_type"] == "COMPLETE_OPERATION"
    assert loaded.domain_state["production_units"]["u1"]["state"] == "in_station"


def test_checkpoint_atomic_save_and_load(tmp_path: Path) -> None:
    cp = sample_checkpoint()
    cp_path = tmp_path / "checkpoints" / "cp_01.json"

    save_checkpoint(cp, cp_path)
    assert cp_path.exists()

    loaded = load_checkpoint(cp_path)
    assert loaded.simulated_time_ns == cp.simulated_time_ns
    assert loaded.config_hash == cp.config_hash
    assert loaded.root_seed == cp.root_seed


def test_checkpoint_inspect() -> None:
    cp = sample_checkpoint()
    inspection = inspect_checkpoint(cp)
    assert isinstance(inspection, CheckpointInspection)
    assert inspection.schema_version == "1.0"
    assert inspection.kernel_version == "1.0"
    assert inspection.model_hash == "abc123model"
    assert inspection.config_hash == "def456config"
    assert inspection.simulated_time_ns == 5_000_000_000
    assert inspection.next_sequence == 42
    assert inspection.sequence_counter == 42
    assert inspection.events_processed == 10
    assert inspection.queue_size == 1
    assert inspection.root_seed == 42
    assert inspection.random_occurrence_counters == {"arrival_stream": 5}
    assert inspection.plugin_metadata == {}

    inspection_dict = inspection.to_dict()
    assert inspection_dict["queue_size"] == 1
    assert inspection_dict["simulated_time_ns"] == 5_000_000_000


def test_checkpoint_partial_or_corrupt_file_rejected(tmp_path: Path) -> None:
    corrupt_file = tmp_path / "corrupt.json"
    corrupt_file.write_text('{"schema_version": "1.0", "kernel_version": ', encoding="utf-8")

    with pytest.raises(InvalidCheckpointError, match=r"(?i)failed|corrupted|invalid"):
        load_checkpoint(corrupt_file)


def test_checkpoint_tampered_checksum_rejected() -> None:
    cp = sample_checkpoint()
    serialized = serialize_checkpoint(cp)
    data = json.loads(serialized)
    # Tamper with simulated_time_ns without updating checksum
    data["simulated_time_ns"] = 999_999_999
    tampered = json.dumps(data)

    with pytest.raises(InvalidCheckpointError, match="checksum|integrity"):
        deserialize_checkpoint(tampered)


def test_checkpoint_atomic_write_leaves_no_partial_file_on_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cp = sample_checkpoint()
    target_path = tmp_path / "checkpoints" / "aborted_cp.json"

    import os
    def failing_fsync(fd: int) -> None:
        raise OSError("Simulated disk failure during write")

    monkeypatch.setattr(os, "fsync", failing_fsync)

    with pytest.raises(OSError, match="Simulated disk failure"):
        save_checkpoint(cp, target_path)

    # Target path should NOT exist because the atomic replace never happened
    assert not target_path.exists()
    # And no lingering temp files in directory
    temp_files = list((tmp_path / "checkpoints").glob(".*.tmp"))
    assert len(temp_files) == 0


def test_checkpoint_inspect_nonexistent_file_raises_error(tmp_path: Path) -> None:
    nonexistent = tmp_path / "does_not_exist.json"
    with pytest.raises(InvalidCheckpointError, match="file not found"):
        inspect_checkpoint(nonexistent)

    with pytest.raises(InvalidCheckpointError, match="file not found"):
        inspect_checkpoint("also_does_not_exist.json")


def test_create_checkpoint_past_time_rejected() -> None:
    from industrialsim.application import EpisodeEngine, create_checkpoint, validate_config

    cfg_yaml = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "10s"
  end_condition:
    type: "max_time"
    max_time: "30s"
stations:
  - id: station-1
    operations:
      - id: op-1
        duration: "5s"
production_units:
  - id: u-1
    variant: "widget"
    release_time: "10s"
"""
    # Requesting a checkpoint before episode start time (10s)
    with pytest.raises(ValueError, match=r"start time is 10000000000 ns"):
        create_checkpoint(cfg_yaml, at_time_ns=5_000_000_000)

    # Running an engine to 20s and requesting checkpoint at 15s
    validation = validate_config(cfg_yaml)
    assert validation.config is not None
    engine = EpisodeEngine.create(validation.config)
    engine.run(pause_at_ns=20_000_000_000)
    with pytest.raises(ValueError, match=r"already advanced past this time"):
        create_checkpoint(engine, at_time_ns=15_000_000_000)


