from __future__ import annotations

import pytest

from industrialsim.config import RouteConfig
from industrialsim.domain import (
    ProductionUnit,
    TransportOrder,
    Vehicle,
)
from industrialsim.dispatch import (
    BaselineDispatchPolicy,
    DispatchContext,
    DispatchDecision,
)


def test_dispatch_policy_nearest_vehicle_and_shortest_route() -> None:
    policy = BaselineDispatchPolicy()

    order = TransportOrder(
        id="to-1",
        unit_id="u-1",
        source_node_id="st-1",
        target_node_id="st-2",
        created_time_ns=0,
    )
    unit = ProductionUnit(id="u-1", variant="sedan")

    # Routes:
    # r-fast: 5s transit
    # r-slow: 10s transit
    r_fast = RouteConfig(
        id="r-fast",
        source_node_id="st-1",
        source_port_id="out",
        target_node_id="st-2",
        target_port_id="in",
        transit_time="5s",
        capacity=1,
    )
    r_slow = RouteConfig(
        id="r-slow",
        source_node_id="st-1",
        source_port_id="out",
        target_node_id="st-2",
        target_port_id="in",
        transit_time="10s",
        capacity=1,
    )

    # Vehicles:
    # v-near: at st-1 (distance 0 to pickup st-1)
    # v-far: at src-1 (distance 5s to pickup st-1)
    v_near = Vehicle(id="v-near", initial_location="st-1", location="st-1")
    v_far = Vehicle(id="v-far", initial_location="src-1", location="src-1")

    distances = {
        ("st-1", "st-1"): 0,
        ("src-1", "st-1"): 5_000_000_000,
    }

    def dist_fn(from_node: str, to_node: str) -> int | None:
        return distances.get((from_node, to_node))

    # Case 1: Both routes available, both vehicles available
    # Policy should choose nearest vehicle (v-near, dist 0) and shortest route (r-fast, 5s)
    decision = policy.select_dispatch(
        order=order,
        unit=unit,
        candidate_routes=[r_slow, r_fast],
        available_vehicles=[v_far, v_near],
        active_route_occupancy={},
        node_distance_fn=dist_fn,
        can_accept_fn=lambda nid: True,
    )
    assert decision is not None
    assert decision.route.id == "r-fast"
    assert decision.vehicle is not None
    assert decision.vehicle.id == "v-near"
    assert decision.pickup_distance_ns == 0


def test_dispatch_policy_route_capacity_and_alternative_routing() -> None:
    policy = BaselineDispatchPolicy()

    order = TransportOrder(
        id="to-2",
        unit_id="u-2",
        source_node_id="st-1",
        target_node_id="st-2",
        created_time_ns=100,
    )
    unit = ProductionUnit(id="u-2", variant="sedan")

    r_fast = RouteConfig(
        id="r-fast",
        source_node_id="st-1",
        source_port_id="out",
        target_node_id="st-2",
        target_port_id="in",
        transit_time="5s",
        capacity=1,
    )
    r_slow = RouteConfig(
        id="r-slow",
        source_node_id="st-1",
        source_port_id="out",
        target_node_id="st-2",
        target_port_id="in",
        transit_time="10s",
        capacity=1,
    )

    v1 = Vehicle(id="v-1", initial_location="st-1", location="st-1")

    def dist_fn(from_node: str, to_node: str) -> int | None:
        return 0 if from_node == to_node else 1000

    # r-fast is at capacity (occupancy = 1 == capacity)
    # Policy should choose alternative admissible route r-slow!
    decision = policy.select_dispatch(
        order=order,
        unit=unit,
        candidate_routes=[r_fast, r_slow],
        available_vehicles=[v1],
        active_route_occupancy={"r-fast": 1},
        node_distance_fn=dist_fn,
        can_accept_fn=lambda nid: True,
    )
    assert decision is not None
    assert decision.route.id == "r-slow"
    assert decision.vehicle is not None
    assert decision.vehicle.id == "v-1"


def test_dispatch_policy_deterministic_tie_breaking() -> None:
    policy = BaselineDispatchPolicy()

    order = TransportOrder(
        id="to-3",
        unit_id="u-3",
        source_node_id="st-1",
        target_node_id="st-2",
        created_time_ns=0,
    )
    unit = ProductionUnit(id="u-3", variant="sedan")

    # Identical transit times on two parallel routes
    r_b = RouteConfig(
        id="r-b",
        source_node_id="st-1",
        source_port_id="out",
        target_node_id="st-2",
        target_port_id="in",
        transit_time="5s",
    )
    r_a = RouteConfig(
        id="r-a",
        source_node_id="st-1",
        source_port_id="out",
        target_node_id="st-2",
        target_port_id="in",
        transit_time="5s",
    )

    # Two identical vehicles at the same location
    v_z = Vehicle(id="v-z", initial_location="st-1", location="st-1")
    v_a = Vehicle(id="v-a", initial_location="st-1", location="st-1")

    decision = policy.select_dispatch(
        order=order,
        unit=unit,
        candidate_routes=[r_b, r_a],
        available_vehicles=[v_z, v_a],
        active_route_occupancy={},
        node_distance_fn=lambda f, t: 0,
        can_accept_fn=lambda nid: True,
    )
    assert decision is not None
    # r-a < r-b tie-break
    assert decision.route.id == "r-a"
    # v-a < v-z tie-break
    assert decision.vehicle is not None
    assert decision.vehicle.id == "v-a"


def test_dispatch_policy_with_dispatch_context() -> None:
    policy = BaselineDispatchPolicy()
    order = TransportOrder(
        id="to-ctx",
        unit_id="u-ctx",
        source_node_id="src-1",
        target_node_id="st-1",
        created_time_ns=0,
    )
    route = RouteConfig(
        id="r-1",
        source_node_id="src-1",
        source_port_id="out",
        target_node_id="st-1",
        target_port_id="in",
        transit_time="5s",
    )
    vehicle = Vehicle(id="v-1", initial_location="src-1", location="src-1")

    ctx = DispatchContext(
        order=order,
        candidate_routes=[route],
        available_vehicles=[vehicle],
        active_route_occupancy={},
        node_distance_fn=lambda f, t: 0,
        can_accept_fn=lambda nid: True,
    )
    decision = policy.select_dispatch(ctx)
    assert decision is not None
    assert decision.route.id == "r-1"
    assert decision.vehicle is not None
    assert decision.vehicle.id == "v-1"


def test_dispatch_policy_shortest_route_priority_over_pickup_distance() -> None:
    # Route A is short (5s), vehicle A is 1s away.
    # Route B is long (20s), vehicle B is 0s away.
    # Policy must choose shortest admissible route (Route A) rather than picking
    # an arbitrarily longer route just because vehicle B is at distance 0.
    policy = BaselineDispatchPolicy()
    order = TransportOrder(
        id="to-4",
        unit_id="u-4",
        source_node_id="st-1",
        target_node_id="st-2",
        created_time_ns=0,
    )
    r_short = RouteConfig(
        id="r-short",
        source_node_id="st-1",
        source_port_id="out",
        target_node_id="st-2",
        target_port_id="in",
        transit_time="5s",
    )
    r_long = RouteConfig(
        id="r-long",
        source_node_id="st-1",
        source_port_id="out",
        target_node_id="st-2",
        target_port_id="in",
        transit_time="20s",
    )
    v_at_pickup = Vehicle(id="v-at-pickup", initial_location="st-1", location="st-1")
    v_farther = Vehicle(id="v-farther", initial_location="src-1", location="src-1")

    distances = {
        ("st-1", "st-1"): 0,
        ("src-1", "st-1"): 1_000_000_000,  # 1s away
    }

    ctx = DispatchContext(
        order=order,
        candidate_routes=[r_long, r_short],
        available_vehicles=[v_at_pickup, v_farther],
        active_route_occupancy={},
        node_distance_fn=lambda f, t: distances.get((f, t)),
        can_accept_fn=lambda nid: True,
    )
    decision = policy.select_dispatch(ctx)
    assert decision is not None
    assert decision.route.id == "r-short"
    assert decision.vehicle is not None
    assert decision.vehicle.id == "v-at-pickup"


def test_dispatch_policy_speed_multiplier_in_pickup_time() -> None:
    # Vehicle A: raw distance 10s, speed 1.0 -> effective pickup time 10s
    # Vehicle B: raw distance 12s, speed 2.0 -> effective pickup time 6s
    # Policy must select Vehicle B as the nearest available vehicle.
    policy = BaselineDispatchPolicy()
    order = TransportOrder(
        id="to-5",
        unit_id="u-5",
        source_node_id="st-1",
        target_node_id="st-2",
        created_time_ns=0,
    )
    route = RouteConfig(
        id="r-1",
        source_node_id="st-1",
        source_port_id="out",
        target_node_id="st-2",
        target_port_id="in",
        transit_time="5s",
    )
    v_a = Vehicle(id="v-a", initial_location="loc-a", location="loc-a", speed_multiplier=1.0)
    v_b = Vehicle(id="v-b", initial_location="loc-b", location="loc-b", speed_multiplier=2.0)

    distances = {
        ("loc-a", "st-1"): 10_000_000_000,
        ("loc-b", "st-1"): 12_000_000_000,
    }

    ctx = DispatchContext(
        order=order,
        candidate_routes=[route],
        available_vehicles=[v_a, v_b],
        active_route_occupancy={},
        node_distance_fn=lambda f, t: distances.get((f, t)),
        can_accept_fn=lambda nid: True,
    )
    decision = policy.select_dispatch(ctx)
    assert decision is not None
    assert decision.vehicle is not None
    assert decision.vehicle.id == "v-b"


def test_dispatch_policy_reserved_route_occupancy_blocks_dispatch() -> None:
    policy = BaselineDispatchPolicy()
    order = TransportOrder(
        id="to-6",
        unit_id="u-6",
        source_node_id="st-1",
        target_node_id="st-2",
        created_time_ns=0,
    )
    route = RouteConfig(
        id="r-1",
        source_node_id="st-1",
        source_port_id="out",
        target_node_id="st-2",
        target_port_id="in",
        transit_time="5s",
        capacity=1,
    )
    vehicle = Vehicle(id="v-1", initial_location="st-1", location="st-1")

    # Route active occupancy is 0, but reserved occupancy is 1 (capacity is 1)
    ctx = DispatchContext(
        order=order,
        candidate_routes=[route],
        available_vehicles=[vehicle],
        active_route_occupancy={"r-1": 0},
        reserved_route_occupancy={"r-1": 1},
        node_distance_fn=lambda f, t: 0,
        can_accept_fn=lambda nid: True,
    )
    decision = policy.select_dispatch(ctx)
    assert decision is None

