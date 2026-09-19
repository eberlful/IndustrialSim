from hypothesis import given, settings, strategies as st
from industrialsim.application import run_episode


def generate_contention_yaml(
    op1_duration_s: int,
    op2_duration_s: int,
    op3_duration_s: int,
    release1_s: int,
    release2_s: int,
    release3_s: int,
) -> str:
    return f"""schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"

machines:
  - id: "mach-shared"
    capacity: 1

workers:
  - id: "worker-pool-shared"
    kind: "pool"
    capacity: 2
    qualifications: ["operator"]

material_flow:
  nodes:
    - id: "src-A"
      kind: "source"
      output_ports:
        - id: "p-out"
          port_type: "part"
          direction: "output"
    - id: "src-B"
      kind: "source"
      output_ports:
        - id: "p-out"
          port_type: "part"
          direction: "output"
    - id: "src-C"
      kind: "source"
      output_ports:
        - id: "p-out"
          port_type: "part"
          direction: "output"
    - id: "st-A"
      kind: "station"
      operations:
        - id: "op-A"
          duration: "{op1_duration_s}s"
          required_machines: ["mach-shared"]
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
    - id: "st-B"
      kind: "station"
      operations:
        - id: "op-B"
          duration: "{op2_duration_s}s"
          required_machines: ["mach-shared"]
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
    - id: "st-C"
      kind: "station"
      operations:
        - id: "op-C"
          duration: "{op3_duration_s}s"
          required_machines: ["mach-shared"]
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
    - id: "r-src-stA"
      source_node_id: "src-A"
      source_port_id: "p-out"
      target_node_id: "st-A"
      target_port_id: "p-in"
    - id: "r-src-stB"
      source_node_id: "src-B"
      source_port_id: "p-out"
      target_node_id: "st-B"
      target_port_id: "p-in"
    - id: "r-src-stC"
      source_node_id: "src-C"
      source_port_id: "p-out"
      target_node_id: "st-C"
      target_port_id: "p-in"
    - id: "r-stA-snk"
      source_node_id: "st-A"
      source_port_id: "p-out"
      target_node_id: "snk-1"
      target_port_id: "p-in"
    - id: "r-stB-snk"
      source_node_id: "st-B"
      source_port_id: "p-out"
      target_node_id: "snk-1"
      target_port_id: "p-in"
    - id: "r-stC-snk"
      source_node_id: "st-C"
      source_port_id: "p-out"
      target_node_id: "snk-1"
      target_port_id: "p-in"

production_units:
  - id: "unit-1"
    variant: "sedan"
    source_id: "src-A"
    release_time: "{release1_s}s"
  - id: "unit-2"
    variant: "coupe"
    source_id: "src-B"
    release_time: "{release2_s}s"
  - id: "unit-3"
    variant: "suv"
    source_id: "src-C"
    release_time: "{release3_s}s"
"""


@settings(max_examples=25, deadline=None)
@given(
    op1=st.integers(min_value=1, max_value=20),
    op2=st.integers(min_value=1, max_value=20),
    op3=st.integers(min_value=1, max_value=20),
    rel1=st.integers(min_value=0, max_value=10),
    rel2=st.integers(min_value=0, max_value=10),
    rel3=st.integers(min_value=0, max_value=10),
)
def test_hypothesis_resource_contention_and_determinism(
    op1: int,
    op2: int,
    op3: int,
    rel1: int,
    rel2: int,
    rel3: int,
) -> None:
    yaml_text = generate_contention_yaml(op1, op2, op3, rel1, rel2, rel3)

    # Run 1
    summary1 = run_episode(yaml_text)
    # Run 2 for determinism check
    summary2 = run_episode(yaml_text)

    # Invariant 1: Determinism
    assert summary1.to_dict() == summary2.to_dict()
    assert summary1.status == "completed"

    # Invariant 2: Deadlock-free completion
    assert len(summary1.production_units) == 3
    for u in summary1.production_units:
        assert u.state == "terminal"

    # Invariant 3: Capacity bounds and busy time conservation
    # Machine capacity is 1, so machine busy time must equal the sum of op durations
    mach = summary1.machines[0]
    expected_mach_busy_ns = (op1 + op2 + op3) * 1_000_000_000
    assert mach.total_busy_time_ns == expected_mach_busy_ns
    assert mach.operations_completed == 3

    # Worker pool of capacity 2 was utilized by 1 worker per operation
    w = summary1.workers[0]
    assert w.total_busy_time_ns == expected_mach_busy_ns
    assert w.operations_completed == 3

    # Total operations completed across stations
    st_ops = sum(s.operations_completed for s in summary1.stations)
    assert st_ops == 3


ATOMIC_MULTI_RESOURCE_TEMPLATE = """schema_version: "1.0"
seed: 42
episode:
  start_time: "0s"
  end_condition:
    type: "all_units_terminal"

machines:
  - id: "mach-shared"
    capacity: 1

workers:
  - id: "worker-specialist"
    kind: "individual"
    qualifications: ["specialist"]
    shifts:
      - id: "shift-spec"
        start_time: "{shift_start}s"
        end_time: "100s"

material_flow:
  nodes:
    - id: "src-A"
      kind: "source"
      output_ports:
        - id: "p-out"
          port_type: "part"
          direction: "output"
    - id: "src-B"
      kind: "source"
      output_ports:
        - id: "p-out"
          port_type: "part"
          direction: "output"
    - id: "st-alpha"
      kind: "station"
      operations:
        - id: "op-alpha"
          duration: "{op_alpha}s"
          required_machines: ["mach-shared"]
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
    - id: "st-beta"
      kind: "station"
      operations:
        - id: "op-beta"
          duration: "{op_beta}s"
          required_machines: ["mach-shared"]
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
    - id: "r-src-alpha"
      source_node_id: "src-A"
      source_port_id: "p-out"
      target_node_id: "st-alpha"
      target_port_id: "p-in"
    - id: "r-src-beta"
      source_node_id: "src-B"
      source_port_id: "p-out"
      target_node_id: "st-beta"
      target_port_id: "p-in"
    - id: "r-alpha-snk"
      source_node_id: "st-alpha"
      source_port_id: "p-out"
      target_node_id: "snk-1"
      target_port_id: "p-in"
    - id: "r-beta-snk"
      source_node_id: "st-beta"
      source_port_id: "p-out"
      target_node_id: "snk-1"
      target_port_id: "p-in"

production_units:
  - id: "unit-alpha"
    variant: "sedan"
    source_id: "src-A"
    release_time: "0s"
  - id: "unit-beta"
    variant: "coupe"
    source_id: "src-B"
    release_time: "0s"
"""


@settings(max_examples=25, deadline=None)
@given(
    op_alpha=st.integers(min_value=2, max_value=15),
    op_beta=st.integers(min_value=1, max_value=10),
    shift_start=st.integers(min_value=1, max_value=10),
)
def test_hypothesis_atomic_multi_resource_allocations_and_zero_partial_reservations(
    op_alpha: int,
    op_beta: int,
    shift_start: int,
) -> None:
    yaml_text = ATOMIC_MULTI_RESOURCE_TEMPLATE.format(
        op_alpha=op_alpha,
        op_beta=op_beta,
        shift_start=shift_start,
    )

    summary = run_episode(yaml_text)
    assert summary.status == "completed"

    st_alpha = next(s for s in summary.stations if s.id == "st-alpha")
    st_beta = next(s for s in summary.stations if s.id == "st-beta")

    # Invariant: st-beta required only mach-shared. Even though st-alpha was also at 0s,
    # st-alpha could NOT acquire mach-shared partially because worker-specialist was not on shift.
    # Therefore, st-beta never waited for mach-shared at 0s!
    assert st_beta.total_waiting_time_ns == 0
    assert st_beta.operations_completed == 1
    assert st_beta.total_busy_time_ns == op_beta * 1_000_000_000

    # st-alpha completed its operation
    assert st_alpha.operations_completed == 1
    assert st_alpha.total_busy_time_ns == op_alpha * 1_000_000_000

    # Total machine busy time equals both operations
    mach = summary.machines[0]
    assert mach.total_busy_time_ns == (op_alpha + op_beta) * 1_000_000_000
    assert mach.operations_completed == 2
