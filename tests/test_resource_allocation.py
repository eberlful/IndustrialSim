import pytest
from industrialsim.application import run_episode


ATOMIC_ALLOCATION_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"

machines:
  - id: "mach-1"
    capacity: 1

workers:
  - id: "worker-specialist"
    kind: "individual"
    qualifications: ["specialist"]
    shifts:
      - id: "shift-all"
        start_time: "0s"
        end_time: "100s"

material_flow:
  nodes:
    - id: "src-1"
      kind: "source"
      output_ports:
        - id: "p-out"
          port_type: "part"
          direction: "output"
    - id: "st-contender-1"
      kind: "station"
      operations:
        - id: "op-needs-both"
          duration: "10s"
          required_machines: ["mach-1"]
          required_workers:
            - qualification: "specialist"
              count: 1
      input_ports:
        - id: "p-in"
          port_type: "part"
          direction: "input"
      output_ports:
        - id: "p-out"
          port_type: "part"
          direction: "output"
    - id: "st-contender-2"
      kind: "station"
      operations:
        - id: "op-needs-mach-only"
          duration: "4s"
          required_machines: ["mach-1"]
      input_ports:
        - id: "p-in"
          port_type: "part"
          direction: "input"
      output_ports:
        - id: "p-out"
          port_type: "part"
          direction: "output"
    - id: "snk-1"
      kind: "sink"
      input_ports:
        - id: "p-in"
          port_type: "part"
          direction: "input"
  routes:
    - id: "r-src-st1"
      source_node_id: "src-1"
      source_port_id: "p-out"
      target_node_id: "st-contender-1"
      target_port_id: "p-in"
    - id: "r-src-st2"
      source_node_id: "src-1"
      source_port_id: "p-out"
      target_node_id: "st-contender-2"
      target_port_id: "p-in"
    - id: "r-st1-snk"
      source_node_id: "st-contender-1"
      source_port_id: "p-out"
      target_node_id: "snk-1"
      target_port_id: "p-in"
    - id: "r-st2-snk"
      source_node_id: "st-contender-2"
      source_port_id: "p-out"
      target_node_id: "snk-1"
      target_port_id: "p-in"

production_units:
  - id: "unit-1"
    variant: "sedan"
    source_id: "src-1"
    release_time: "0s"
  - id: "unit-2"
    variant: "suv"
    source_id: "src-1"
    release_time: "0s"
"""


def test_atomic_allocation_prevents_partial_reservation_and_exposes_metrics() -> None:
    # In this scenario, we give worker-specialist a shift that starts at 5s.
    # At 0s, mach-1 is free, but worker-specialist is NOT on shift until 5s.
    # Unit 1 is at st-contender-1 (needs mach-1 and worker-specialist).
    # Because worker is unavailable, st-contender-1 CANNOT acquire mach-1 partially!
    # Unit 2 is at st-contender-2 (needs mach-1 only).
    # Since st-contender-1 did NOT lock/reserve mach-1, st-contender-2 acquires mach-1 at 0s,
    # and runs for 4s (from 0s to 4s).
    # At 4s, st-contender-2 finishes, releases mach-1.
    # At 5s, worker-specialist's shift starts. Now both mach-1 and worker-specialist are free!
    # st-contender-1 acquires both atomically at 5s, runs for 10s (5s to 15s), and finishes at 15s.
    yaml_delayed_worker = ATOMIC_ALLOCATION_YAML.replace(
        'start_time: "0s"\n        end_time: "100s"',
        'start_time: "5s"\n        end_time: "100s"',
    )

    summary = run_episode(yaml_delayed_worker)
    assert summary.status == "completed"
    assert summary.simulated_time_ns == 15_000_000_000

    # Verify Station metrics
    st1 = next(s for s in summary.stations if s.id == "st-contender-1")
    assert st1.operations_completed == 1
    assert st1.total_busy_time_ns == 10_000_000_000
    # st-contender-1 had unit-1 at 0s, but could only start at 5s -> waited 5s
    assert st1.total_waiting_time_ns == 5_000_000_000

    st2 = next(s for s in summary.stations if s.id == "st-contender-2")
    assert st2.operations_completed == 1
    assert st2.total_busy_time_ns == 4_000_000_000
    # st-contender-2 acquired mach-1 at 0s immediately -> 0 waiting time
    assert st2.total_waiting_time_ns == 0

    # Verify Machine metrics exposed at application level
    assert len(summary.machines) == 1
    mach = summary.machines[0]
    assert mach.id == "mach-1"
    assert mach.capacity == 1
    assert mach.operations_completed == 2
    # mach-1 was busy for st2 (0..4s = 4s) and st1 (5..15s = 10s) -> 14s total
    assert mach.total_busy_time_ns == 14_000_000_000
    assert mach.total_idle_time_ns == 1_000_000_000  # 4s to 5s
    assert pytest.approx(mach.utilization, 0.001) == 14.0 / 15.0

    # Verify Worker metrics exposed at application level
    assert len(summary.workers) == 1
    w = summary.workers[0]
    assert w.id == "worker-specialist"
    assert w.capacity == 1
    assert w.operations_completed == 1
    assert w.total_busy_time_ns == 10_000_000_000
    assert w.total_off_shift_time_ns == 5_000_000_000  # 0s to 5s was off-shift


def test_deterministic_contention_for_simultaneous_requests() -> None:
    # Two units arriving simultaneously at stations contending for the same machine mach-1
    # Both need mach-1 only. st-contender-1 has duration 10s, st-contender-2 has duration 4s.
    # Contender tie-breaking must be strictly deterministic!
    summary_1 = run_episode(ATOMIC_ALLOCATION_YAML)
    summary_2 = run_episode(ATOMIC_ALLOCATION_YAML)

    assert summary_1.status == "completed"
    assert summary_1.result_hash == summary_2.result_hash
    assert summary_1.simulated_time_ns == summary_2.simulated_time_ns
    assert summary_1.to_dict() == summary_2.to_dict()
