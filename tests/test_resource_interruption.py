import pytest
from industrialsim.application import run_episode


HANDOVER_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"

workers:
  - id: "worker-shift-1"
    kind: "individual"
    qualifications: ["operator"]
    shifts:
      - id: "shift-morning"
        start_time: "0s"
        end_time: "5s"
        handover_rule: "handover"
  - id: "worker-shift-2"
    kind: "individual"
    qualifications: ["operator"]
    shifts:
      - id: "shift-evening"
        start_time: "5s"
        end_time: "15s"
        handover_rule: "handover"

material_flow:
  nodes:
    - id: "src-1"
      kind: "source"
      output_ports:
        - id: "p-out"
          port_type: "part"
          direction: "output"
    - id: "st-1"
      kind: "station"
      operations:
        - id: "op-long"
          duration: "10s"
          interruption_policy: "resume"
          required_workers:
            - qualification: "operator"
              count: 1
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
      target_node_id: "st-1"
      target_port_id: "p-in"
    - id: "r-st1-snk"
      source_node_id: "st-1"
      source_port_id: "p-out"
      target_node_id: "snk-1"
      target_port_id: "p-in"

production_units:
  - id: "unit-1"
    variant: "sedan"
    source_id: "src-1"
    release_time: "0s"
"""


def test_shift_handover_uninterrupted() -> None:
    # Operation is 10s. Shift 1 runs from 0s to 5s. Shift 2 starts at 5s.
    # Handover rule is "handover" -> worker-shift-2 takes over at 5s seamlessly.
    # No interruption occurs. Station finishes at 10s.
    summary = run_episode(HANDOVER_YAML)
    assert summary.status == "completed"
    assert summary.simulated_time_ns == 10_000_000_000

    st = summary.stations[0]
    assert st.operations_completed == 1
    assert st.interrupted_count == 0
    assert st.resumed_count == 0
    assert st.total_waiting_time_ns == 0
    assert st.total_busy_time_ns == 10_000_000_000

    # Both workers should have worked 5s
    w1 = next(w for w in summary.workers if w.id == "worker-shift-1")
    w2 = next(w for w in summary.workers if w.id == "worker-shift-2")
    assert w1.total_busy_time_ns == 5_000_000_000
    assert w2.total_busy_time_ns == 5_000_000_000


RESUME_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"

workers:
  - id: "worker-solo"
    kind: "individual"
    qualifications: ["operator"]
    shifts:
      - id: "shift-1"
        start_time: "0s"
        end_time: "4s"
        handover_rule: "interrupt"
      - id: "shift-2"
        start_time: "8s"
        end_time: "15s"
        handover_rule: "interrupt"

material_flow:
  nodes:
    - id: "src-1"
      kind: "source"
      output_ports:
        - id: "p-out"
          port_type: "part"
          direction: "output"
    - id: "st-1"
      kind: "station"
      operations:
        - id: "op-1"
          duration: "10s"
          interruption_policy: "resume"
          required_workers:
            - qualification: "operator"
              count: 1
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
      target_node_id: "st-1"
      target_port_id: "p-in"
    - id: "r-st1-snk"
      source_node_id: "st-1"
      source_port_id: "p-out"
      target_node_id: "snk-1"
      target_port_id: "p-in"

production_units:
  - id: "unit-1"
    variant: "sedan"
    source_id: "src-1"
    release_time: "0s"
"""


def test_interruption_policy_resume() -> None:
    # Op duration = 10s.
    # Worker runs 0s to 4s (4s elapsed, 6s remaining).
    # Interrupted at 4s due to shift end.
    # Worker returns at 8s. Resumes remaining 6s -> finishes at 8s + 6s = 14s.
    summary = run_episode(RESUME_YAML)
    assert summary.status == "completed"
    assert summary.simulated_time_ns == 14_000_000_000

    st = summary.stations[0]
    assert st.operations_completed == 1
    assert st.interrupted_count == 1
    assert st.resumed_count == 1
    assert st.restarted_count == 0
    assert st.scrapped_count == 0
    # Busy time: 4s before interruption + 6s after resumption = 10s
    assert st.total_busy_time_ns == 10_000_000_000
    # Waiting time: from 4s to 8s = 4s
    assert st.total_waiting_time_ns == 4_000_000_000


RESTART_YAML = RESUME_YAML.replace(
    'interruption_policy: "resume"',
    'interruption_policy: "restart"',
).replace(
    'start_time: "8s"\n        end_time: "15s"',
    'start_time: "8s"\n        end_time: "25s"',
)


def test_interruption_policy_restart() -> None:
    # Op duration = 10s.
    # Worker runs 0s to 4s (4s discarded!).
    # Interrupted at 4s due to shift end.
    # Worker returns at 8s. Restarts from beginning (10s duration) -> finishes at 8s + 10s = 18s.
    summary = run_episode(RESTART_YAML)
    assert summary.status == "completed"
    assert summary.simulated_time_ns == 18_000_000_000

    st = summary.stations[0]
    assert st.operations_completed == 1
    assert st.interrupted_count == 1
    assert st.resumed_count == 0
    assert st.restarted_count == 1
    assert st.scrapped_count == 0
    # Busy time: 4s before restart + 10s restarted = 14s
    assert st.total_busy_time_ns == 14_000_000_000
    # Waiting time: from 4s to 8s = 4s
    assert st.total_waiting_time_ns == 4_000_000_000


SCRAP_YAML = RESUME_YAML.replace('interruption_policy: "resume"', 'interruption_policy: "scrap"')


def test_interruption_policy_scrap() -> None:
    # Op duration = 10s.
    # Worker runs 0s to 4s.
    # Interrupted at 4s -> unit is scrapped immediately and moves to terminal state.
    # Episode completes at 4s because unit is terminal.
    summary = run_episode(SCRAP_YAML)
    assert summary.status == "completed"
    assert summary.simulated_time_ns == 4_000_000_000

    st = summary.stations[0]
    assert st.operations_completed == 0
    assert st.interrupted_count == 1
    assert st.resumed_count == 0
    assert st.restarted_count == 0
    assert st.scrapped_count == 1
    assert st.total_busy_time_ns == 4_000_000_000

    u = summary.production_units[0]
    assert u.state == "terminal"
    assert u.quality_state == "scrapped"


MACHINE_BREAK_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"

machines:
  - id: "mach-1"
    capacity: 1
    breaks:
      - start_time: "3s"
        end_time: "6s"

material_flow:
  nodes:
    - id: "src-1"
      kind: "source"
      output_ports:
        - id: "p-out"
          port_type: "part"
          direction: "output"
    - id: "st-1"
      kind: "station"
      operations:
        - id: "op-1"
          duration: "10s"
          interruption_policy: "resume"
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
      target_node_id: "st-1"
      target_port_id: "p-in"
    - id: "r-st1-snk"
      source_node_id: "st-1"
      source_port_id: "p-out"
      target_node_id: "snk-1"
      target_port_id: "p-in"

production_units:
  - id: "unit-1"
    variant: "sedan"
    source_id: "src-1"
    release_time: "0s"
"""


def test_machine_break_interrupts_and_resumes() -> None:
    # Op duration = 10s. Machine runs 0s to 3s.
    # Break from 3s to 6s (3s pause).
    # Break ends at 6s. Resumes remaining 7s -> finishes at 6s + 7s = 13s.
    summary = run_episode(MACHINE_BREAK_YAML)
    assert summary.status == "completed"
    assert summary.simulated_time_ns == 13_000_000_000

    st = summary.stations[0]
    assert st.operations_completed == 1
    assert st.interrupted_count == 1
    assert st.resumed_count == 1
    assert st.total_busy_time_ns == 10_000_000_000
    assert st.total_waiting_time_ns == 3_000_000_000

    mach = summary.machines[0]
    assert mach.total_busy_time_ns == 10_000_000_000
    assert mach.total_break_time_ns == 3_000_000_000


MACHINE_RUN_OFF_YAML = """
schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"

machines:
  - id: "mach-1"
    capacity: 1
    shifts:
      - id: "shift-1"
        start_time: "0s"
        end_time: "5s"
        handover_rule: "run_off"

material_flow:
  nodes:
    - id: "src-1"
      kind: "source"
      output_ports:
        - id: "p-out"
          port_type: "part"
          direction: "output"
    - id: "st-1"
      kind: "station"
      operations:
        - id: "op-1"
          duration: "8s"
          interruption_policy: "resume"
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
      target_node_id: "st-1"
      target_port_id: "p-in"
    - id: "r-st1-snk"
      source_node_id: "st-1"
      source_port_id: "p-out"
      target_node_id: "snk-1"
      target_port_id: "p-in"

production_units:
  - id: "unit-1"
    variant: "sedan"
    source_id: "src-1"
    release_time: "0s"
"""


def test_machine_run_off_allows_completion_without_interruption() -> None:
    # Op duration = 8s. Machine shift ends at 5s with handover_rule="run_off".
    # The active operation is allowed to complete without interruption.
    summary = run_episode(MACHINE_RUN_OFF_YAML)
    assert summary.status == "completed"
    assert summary.simulated_time_ns == 8_000_000_000

    st = summary.stations[0]
    assert st.operations_completed == 1
    assert st.interrupted_count == 0
    assert st.total_busy_time_ns == 8_000_000_000

    mach = summary.machines[0]
    assert mach.operations_completed == 1
    assert mach.total_busy_time_ns == 8_000_000_000
