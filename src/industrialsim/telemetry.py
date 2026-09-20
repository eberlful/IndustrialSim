from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence
import pyarrow as pa
import pyarrow.parquet as pq

from industrialsim.config import TelemetryConfig


METRICS_TELEMETRY_SCHEMA = pa.schema([
    ("simulated_time_ns", pa.int64()),
    ("episode_id", pa.string()),
    ("sample_type", pa.string()),
    ("event_name", pa.string()),
    ("good_output", pa.int64()),
    ("scrap", pa.int64()),
    ("wip", pa.int64()),
    ("lead_time_ns", pa.int64()),
    ("downtime_ns", pa.int64()),
    ("lateness_ns", pa.int64()),
    ("machines_busy", pa.int64()),
    ("machines_idle", pa.int64()),
    ("machines_failed", pa.int64()),
    ("workers_busy", pa.int64()),
    ("workers_idle", pa.int64()),
    ("vehicles_busy", pa.int64()),
    ("vehicles_idle", pa.int64()),
    ("current_reward", pa.float64()),
])

TRAINING_RECORDS_SCHEMA = pa.schema([
    ("simulated_time_ns", pa.int64()),
    ("episode_id", pa.string()),
    ("batch_id", pa.string()),
    ("request_id", pa.string()),
    ("request_type", pa.string()),
    ("target_id", pa.string()),
    ("action_type", pa.string()),
    ("action_payload_json", pa.string()),
    ("provider_id", pa.string()),
    ("reward", pa.float64()),
    ("is_terminal", pa.bool_()),
])


class TelemetryManager:
    def __init__(
        self,
        output_dir: Path | str | None,
        config: TelemetryConfig | None,
        episode_id: str,
    ) -> None:
        self.output_dir = Path(output_dir) if output_dir is not None else None
        self.config = config
        self.episode_id = episode_id
        self._enabled = config.enabled if config is not None else False
        self._metrics_buffer: list[dict[str, Any]] = []
        self._training_buffer: list[dict[str, Any]] = []
        self._metrics_fragment_index = 0
        self._training_fragment_index = 0
        self._thinned_samples_count = 0
        self._metrics_records_written = 0
        self._training_records_written = 0
        self._metrics_fragment_paths: list[str] = []
        self._training_fragment_paths: list[str] = []

        self.telemetry_dir: Path | None = None
        if self.output_dir is not None:
            self.telemetry_dir = self.output_dir / "telemetry"
            self.telemetry_dir.mkdir(parents=True, exist_ok=True)

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    @property
    def thinned_samples_count(self) -> int:
        return self._thinned_samples_count

    @property
    def metrics_records_written(self) -> int:
        return self._metrics_records_written

    @property
    def training_records_written(self) -> int:
        return self._training_records_written

    @property
    def metrics_fragment_paths(self) -> list[str]:
        return list(self._metrics_fragment_paths)

    @property
    def training_fragment_paths(self) -> list[str]:
        return list(self._training_fragment_paths)

    def record_metrics_sample(self, sample: dict[str, Any]) -> bool:
        if not self._enabled:
            return False

        bp = self.config.backpressure if self.config else None
        if bp is not None and len(self._metrics_buffer) >= bp.max_queue_size:
            if bp.policy == "thin":
                thin_factor = max(2, bp.thin_factor)
                old_len = len(self._metrics_buffer)
                self._metrics_buffer = self._metrics_buffer[::thin_factor]
                dropped = old_len - len(self._metrics_buffer)
                self._thinned_samples_count += dropped
            elif bp.policy == "drop_newest":
                self._thinned_samples_count += 1
                return False
            elif bp.policy == "drop_oldest":
                self._metrics_buffer.pop(0)
                self._thinned_samples_count += 1

        # Format sample adhering to schema
        row = {
            "simulated_time_ns": int(sample.get("simulated_time_ns", 0)),
            "episode_id": self.episode_id,
            "sample_type": str(sample.get("sample_type", "interval")),
            "event_name": sample.get("event_name"),
            "good_output": int(sample.get("good_output", 0)),
            "scrap": int(sample.get("scrap", 0)),
            "wip": int(sample.get("wip", 0)),
            "lead_time_ns": int(sample.get("lead_time_ns", 0)),
            "downtime_ns": int(sample.get("downtime_ns", 0)),
            "lateness_ns": int(sample.get("lateness_ns", 0)),
            "machines_busy": int(sample.get("machines_busy", 0)),
            "machines_idle": int(sample.get("machines_idle", 0)),
            "machines_failed": int(sample.get("machines_failed", 0)),
            "workers_busy": int(sample.get("workers_busy", 0)),
            "workers_idle": int(sample.get("workers_idle", 0)),
            "vehicles_busy": int(sample.get("vehicles_busy", 0)),
            "vehicles_idle": int(sample.get("vehicles_idle", 0)),
            "current_reward": float(sample["current_reward"]) if sample.get("current_reward") is not None else None,
        }
        self._metrics_buffer.append(row)

        batch_size = self.config.batch_size if self.config else 100
        if len(self._metrics_buffer) >= batch_size:
            self._flush_metrics_fragment()

        return True

    def record_training_record(self, record: dict[str, Any]) -> bool:
        if not self._enabled:
            return False

        bp = self.config.backpressure if self.config else None
        if bp is not None and len(self._training_buffer) >= bp.max_queue_size:
            if bp.policy == "thin":
                thin_factor = max(2, bp.thin_factor)
                old_len = len(self._training_buffer)
                self._training_buffer = self._training_buffer[::thin_factor]
                dropped = old_len - len(self._training_buffer)
                self._thinned_samples_count += dropped
            elif bp.policy == "drop_newest":
                self._thinned_samples_count += 1
                return False
            elif bp.policy == "drop_oldest":
                self._training_buffer.pop(0)
                self._thinned_samples_count += 1

        row = {
            "simulated_time_ns": int(record.get("simulated_time_ns", 0)),
            "episode_id": self.episode_id,
            "batch_id": str(record.get("batch_id", "")),
            "request_id": str(record.get("request_id", "")),
            "request_type": str(record.get("request_type", "")),
            "target_id": str(record.get("target_id", "")),
            "action_type": record.get("action_type"),
            "action_payload_json": record.get("action_payload_json"),
            "provider_id": record.get("provider_id"),
            "reward": float(record["reward"]) if record.get("reward") is not None else None,
            "is_terminal": bool(record.get("is_terminal", False)),
        }
        self._training_buffer.append(row)

        batch_size = self.config.batch_size if self.config else 100
        if len(self._training_buffer) >= batch_size:
            self._flush_training_fragment()

        return True

    def _flush_buffer(
        self,
        buffer: list[dict[str, Any]],
        schema: Any,
        prefix: str,
        index: int,
        paths: list[str],
    ) -> tuple[int, int]:
        if not buffer or self.telemetry_dir is None:
            return index, 0

        filename = f"{prefix}_{index:05d}.parquet"
        target_path = self.telemetry_dir / filename
        tmp_path = target_path.with_suffix(".parquet.tmp")

        table = pa.Table.from_pylist(buffer, schema=schema)
        pq.write_table(table, tmp_path)
        tmp_path.rename(target_path)

        rel_path = f"telemetry/{filename}"
        paths.append(rel_path)
        records_count = len(buffer)
        buffer.clear()
        return index + 1, records_count

    def _flush_metrics_fragment(self) -> None:
        self._metrics_fragment_index, written = self._flush_buffer(
            self._metrics_buffer,
            METRICS_TELEMETRY_SCHEMA,
            "metrics_fragment",
            self._metrics_fragment_index,
            self._metrics_fragment_paths,
        )
        self._metrics_records_written += written

    def _flush_training_fragment(self) -> None:
        self._training_fragment_index, written = self._flush_buffer(
            self._training_buffer,
            TRAINING_RECORDS_SCHEMA,
            "training_fragment",
            self._training_fragment_index,
            self._training_fragment_paths,
        )
        self._training_records_written += written

    def close(self) -> None:
        if self._metrics_buffer:
            self._flush_metrics_fragment()
        if self._training_buffer:
            self._flush_training_fragment()
