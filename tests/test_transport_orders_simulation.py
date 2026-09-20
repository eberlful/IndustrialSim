from __future__ import annotations

from pathlib import Path
import pytest

from industrialsim.application import create_checkpoint, resume_episode, run_episode
from industrialsim.domain import ProductionUnitState, VehicleState


VEHICLE_CONTENTION_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
material_flow:
  nodes:
    - id: "src"
      kind: "source"
      output_ports:
        - id: "out"
          port_type: "body"
          direction: "output"
    - id: "st1"
      kind: "station"
      operations:
        - id: "op1"
          duration: "10s"
      input_ports:
        - id: "in"
          port_type: "body"
          direction: "input"
      output_ports:
        - id: "out"
          port_type: "body"
          direction: "output"
    - id: "snk"
      kind: "sink"
      input_ports:
        - id: "in"
          port_type: "body"
          direction: "input"
  routes:
    - id: "r_src_st1"
      source_node_id: "src"
      source_port_id: "out"
      target_node_id: "st1"
      target_port_id: "in"
      transit_time: "5s"
    - id: "r_st1_snk"
      source_node_id: "st1"
      source_port_id: "out"
      target_node_id: "snk"
      target_port_id: "in"
      transit_time: "5s"
production_units:
  - id: "u1"
    variant: "sedan"
    source_id: "src"
    release_time: 0
  - id: "u2"
    variant: "sedan"
    source_id: "src"
    release_time: 0
vehicles:
  - id: "v1"
    initial_location: "src"
"""


def test_vehicle_contention_and_observable_logistics_backpressure() -> None:
    # 2 units released at t=0, but only 1 shared vehicle v1 at src.
    # r_src_st1 takes 5s.
    # Order for u1 is dispatched first to v1 (FIFO).
    # Order for u2 must queue at src until v1 is available.
    # u1 travels on r_src_st1 (0s to 5s), arrives at st1 at 5s.
    # v1 becomes IDLE at st1 at 5s.
    # To pick up u2 at src, v1 must reposition to src (distance 5s, from 5s to 10s).
    # u2 is picked up at src at 10s, arrives at st1 at 15s.
    summary = run_episode(VEHICLE_CONTENTION_YAML)

    assert summary.status == "completed"
    assert len(summary.production_units) == 2
    assert len(summary.vehicles) == 1

    v1 = summary.vehicles[0]
    assert v1.id == "v1"
    assert v1.transports_completed >= 2
    assert v1.total_busy_time_ns > 0

    # Verify visible transport orders
    assert len(summary.transport_orders) >= 4  # (u1: src->st1, st1->snk; u2: src->st1, st1->snk)
    for order in summary.transport_orders:
        assert order.state == "completed"
        assert order.vehicle_id == "v1"
        assert order.dispatched_time_ns is not None
        assert order.completed_time_ns is not None
        assert order.completed_time_ns >= order.dispatched_time_ns


ROUTE_CONTENTION_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: 0
  end_condition:
    type: "all_units_terminal"
material_flow:
  nodes:
    - id: "src"
      kind: "source"
      output_ports:
        - id: "out"
          port_type: "body"
          direction: "output"
    - id: "buf"
      kind: "buffer"
      capacity: 5
      input_ports:
        - id: "in"
          port_type: "body"
          direction: "input"
      output_ports:
        - id: "out"
          port_type: "body"
          direction: "output"
    - id: "snk"
      kind: "sink"
      input_ports:
        - id: "in"
          port_type: "body"
          direction: "input"
  routes:
    - id: "r_fast"
      source_node_id: "src"
      source_port_id: "out"
      target_node_id: "buf"
      target_port_id: "in"
      transit_time: "5s"
      capacity: 1
    - id: "r_slow"
      source_node_id: "src"
      source_port_id: "out"
      target_node_id: "buf"
      target_port_id: "in"
      transit_time: "10s"
      capacity: 1
    - id: "r_buf_snk"
      source_node_id: "buf"
      source_port_id: "out"
      target_node_id: "snk"
      target_port_id: "in"
      transit_time: "2s"
production_units:
  - id: "u1"
    variant: "sedan"
    source_id: "src"
    release_time: 0
  - id: "u2"
    variant: "sedan"
    source_id: "src"
    release_time: 0
vehicles:
  - id: "v1"
    initial_location: "src"
  - id: "v2"
    initial_location: "src"
"""


def test_route_capacity_and_alternative_routing() -> None:
    # 2 units, 2 vehicles at src at t=0.
    # Parallel routes to buf:
    # r_fast (transit 5s, capacity 1)
    # r_slow (transit 10s, capacity 1)
    # Both units need transport from src to buf.
    # Order 1 takes r_fast with v1 (shortest admissible route).
    # Since r_fast capacity is 1, r_fast is congested.
    # Order 2 selects alternative admissible route r_slow with v2!
    summary = run_episode(ROUTE_CONTENTION_YAML)

    assert summary.status == "completed"
    # Find orders from src to buf
    src_orders = [to for to in summary.transport_orders if to.source_node_id == "src"]
    assert len(src_orders) == 2
    route_ids = {to.route_id for to in src_orders}
    assert route_ids == {"r_fast", "r_slow"}


def test_production_unit_single_occupancy_invariant() -> None:
    summary = run_episode(ROUTE_CONTENTION_YAML)

    # Invariant: A Production Unit is in exactly one transport while moving
    # and cannot simultaneously occupy a graph node.
    for u in summary.production_units:
        in_transport_records = [rec for rec in u.history if rec["state"] == str(ProductionUnitState.IN_TRANSPORT)]
        assert len(in_transport_records) >= 1
        for rec in in_transport_records:
            # While in transport, location must be the route, not a node
            assert rec["location"] in {"r_fast", "r_slow", "r_buf_snk"}


def test_transport_reproducible_ordering() -> None:
    summary1 = run_episode(ROUTE_CONTENTION_YAML)
    summary2 = run_episode(ROUTE_CONTENTION_YAML)

    assert summary1.result_hash == summary2.result_hash
    assert summary1.simulated_time_ns == summary2.simulated_time_ns
    assert summary1.events_processed == summary2.events_processed


def test_transport_checkpoint_equivalence(tmp_path: Path) -> None:
    from industrialsim.application import create_checkpoint, resume_episode, run_episode, save_checkpoint

    # Run uninterrupted reference
    ref_summary = run_episode(ROUTE_CONTENTION_YAML)

    # Checkpoint at 3s (mid-transport)
    cp = create_checkpoint(ROUTE_CONTENTION_YAML, at_time_ns=3_000_000_000)
    assert cp.simulated_time_ns == 3_000_000_000

    cp_file = tmp_path / "transport_checkpoint.json"
    save_checkpoint(cp, cp_file)

    # Resume from checkpoint
    resumed_summary = resume_episode(cp_file)

    assert resumed_summary.result_hash == ref_summary.result_hash
    assert resumed_summary.simulated_time_ns == ref_summary.simulated_time_ns
    assert resumed_summary.events_processed == ref_summary.events_processed
