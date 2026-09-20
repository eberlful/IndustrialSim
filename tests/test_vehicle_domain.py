from __future__ import annotations

import pytest

from industrialsim.domain import (
    TransportOrder,
    TransportOrderState,
    Vehicle,
    VehicleState,
)


def test_vehicle_domain_lifecycle_and_metrics() -> None:
    v = Vehicle(
        id="v-1",
        initial_location="src-1",
        location="src-1",
        pool_id="agv_pool",
        capabilities=["agv"],
    )

    assert v.is_available()
    assert v.state == VehicleState.IDLE
    assert v.location == "src-1"
    assert v.utilization == 0.0

    # Start transport
    v.update_metrics(1_000_000_000)  # 1s idle
    v.state = VehicleState.TRANSPORTING
    v.current_order_id = "to-1"
    v.current_unit_id = "u-1"
    v.current_route_id = "r-1"
    assert not v.is_available()

    # Complete transport at target node
    v.update_metrics(3_000_000_000)  # 2s transporting
    v.state = VehicleState.IDLE
    v.location = "st-1"
    v.current_order_id = None
    v.current_unit_id = None
    v.current_route_id = None
    v.transports_completed += 1

    assert v.is_available()
    assert v.location == "st-1"
    assert v.total_idle_time_ns == 1_000_000_000
    assert v.total_busy_time_ns == 2_000_000_000
    assert v.transports_completed == 1
    assert v.utilization == pytest.approx(2.0 / 3.0)

    # Snapshot and restore
    snap = v.to_snapshot()
    v2 = Vehicle(
        id="v-1",
        initial_location="src-1",
        location="src-1",
    )
    v2.restore_state(snap)
    assert v2.location == "st-1"
    assert v2.total_idle_time_ns == 1_000_000_000
    assert v2.total_busy_time_ns == 2_000_000_000
    assert v2.transports_completed == 1


def test_transport_order_domain_lifecycle() -> None:
    order = TransportOrder(
        id="to-1",
        unit_id="u-1",
        source_node_id="src-1",
        target_node_id="st-1",
        created_time_ns=100,
    )

    assert order.state == TransportOrderState.PENDING
    assert order.assigned_vehicle_id is None
    assert order.assigned_route_id is None

    # Dispatch
    order.dispatch(vehicle_id="v-1", route_id="r-1", time_ns=200)
    assert order.state == TransportOrderState.DISPATCHED
    assert order.assigned_vehicle_id == "v-1"
    assert order.assigned_route_id == "r-1"
    assert order.dispatched_time_ns == 200

    # Pickup
    order.pickup(time_ns=250)
    assert order.state == TransportOrderState.IN_TRANSIT
    assert order.pickup_time_ns == 250

    # Complete
    order.complete(time_ns=500)
    assert order.state == TransportOrderState.COMPLETED
    assert order.completed_time_ns == 500

    # Snapshot round-trip
    snap = order.to_snapshot()
    restored = TransportOrder.from_snapshot(snap)
    assert restored.id == order.id
    assert restored.unit_id == order.unit_id
    assert restored.state == TransportOrderState.COMPLETED
    assert restored.dispatched_time_ns == 200
    assert restored.completed_time_ns == 500
