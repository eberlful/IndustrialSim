import pytest
from industrialsim.domain import (
    Operation,
    ProductionUnit,
    QualityFinding,
    Station,
    StandardTimingPolicy,
    StandardResourceDemandPolicy,
    StandardQualityPolicy,
    StandardDegradationPolicy,
    StandardFailurePolicy,
    TimingPolicy,
    ResourceDemandPolicy,
    QualityPolicy,
)
from industrialsim.material_flow import Port, PortDirection


def test_station_thin_abstraction_ports_and_state():
    in_port = Port(id="in", port_type="body", direction=PortDirection.INPUT)
    out_port = Port(id="out", port_type="body", direction=PortDirection.OUTPUT)
    op = Operation(id="weld", duration_ns=10_000_000_000)

    st = Station(
        id="st_1",
        operations={"weld": op},
        input_ports={"in": in_port},
        output_ports={"out": out_port},
    )

    # Identity
    assert st.id == "st_1"

    # Typed Ports
    assert st.get_port("in") == in_port
    assert st.get_port("out") == out_port
    assert st.input_ports["in"].direction == PortDirection.INPUT
    assert st.output_ports["out"].direction == PortDirection.OUTPUT

    # Observable State
    assert not st.is_busy
    assert not st.is_blocked
    assert st.current_unit_id is None
    assert st.operations_completed == 0

    st.start_operation("unit-1", "weld", start_time_ns=1_000_000_000)
    assert st.is_busy
    assert st.current_unit_id == "unit-1"

    st.complete_operation("weld", completion_time_ns=11_000_000_000)
    assert not st.is_busy
    assert st.current_unit_id is None
    assert st.operations_completed == 1
    assert st.total_busy_time_ns == 10_000_000_000

    # Snapshot and restore preserves ports and state
    snap = st.to_snapshot()
    assert snap["id"] == "st_1"
    assert snap["operations_completed"] == 1
    assert snap["total_busy_time_ns"] == 10_000_000_000

    st_restored = Station(id="st_1", operations={"weld": op})
    st_restored.restore_state(snap)
    assert st_restored.operations_completed == 1
    assert st_restored.total_busy_time_ns == 10_000_000_000


def test_station_composed_policies_defaults():
    op = Operation(id="paint", duration_ns=5_000_000_000, required_machines=["robot_1"])
    st = Station(id="st_paint", operations={"paint": op})

    assert isinstance(st.timing_policy, StandardTimingPolicy)
    assert isinstance(st.resource_policy, StandardResourceDemandPolicy)
    assert isinstance(st.quality_policy, StandardQualityPolicy)
    assert isinstance(st.degradation_policy, StandardDegradationPolicy)
    assert isinstance(st.failure_policy, StandardFailurePolicy)

    unit = ProductionUnit(id="u1", variant="sedan")
    dur = st.timing_policy.compute_duration_ns(op, unit=unit, time_ns=0)
    assert dur == 5_000_000_000

    req_machs = st.resource_policy.get_required_machines(op)
    assert req_machs == ["robot_1"]


def test_station_composed_policies_custom_override():
    class FastTimingPolicy(TimingPolicy):
        def compute_duration_ns(self, operation: Operation, unit: ProductionUnit | None = None, time_ns: int = 0, context=None) -> int:
            return operation.duration_ns // 2

    class CustomQualityPolicy(QualityPolicy):
        def compute_defect(self, operation: Operation, unit: ProductionUnit, time_ns: int = 0, context=None):
            return True, "custom_defect", "scratched"

    op = Operation(id="assemble", duration_ns=6_000_000_000)
    st = Station(
        id="st_custom",
        operations={"assemble": op},
        timing_policy=FastTimingPolicy(),
        quality_policy=CustomQualityPolicy(),
    )

    unit = ProductionUnit(id="u2", variant="suv")
    assert st.timing_policy.compute_duration_ns(op, unit=unit) == 3_000_000_000

    has_defect, name, target = st.quality_policy.compute_defect(op, unit=unit)
    assert has_defect is True
    assert name == "custom_defect"
    assert target == "scratched"
