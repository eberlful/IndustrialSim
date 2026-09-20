from __future__ import annotations

import pytest

from industrialsim.config import RouteConfig
from industrialsim.domain import (
    ProductionUnit,
    TransportOrder,
    Vehicle,
)
from industrialsim.dispatch import BaselineDispatchPolicy, DispatchDecision


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
