from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from industrialsim.config import RouteConfig
from industrialsim.domain import TransportOrder, Vehicle


@dataclass(frozen=True)
class DispatchDecision:
    order: TransportOrder
    route: RouteConfig
    vehicle: Vehicle | None
    pickup_distance_ns: int = 0


@dataclass(frozen=True)
class DispatchContext:
    """Consolidated context parameters for dispatch evaluation, preventing Data Clumps."""

    order: TransportOrder
    candidate_routes: Sequence[RouteConfig]
    available_vehicles: Sequence[Vehicle]
    active_route_occupancy: Mapping[str, int]
    node_distance_fn: Callable[[str, str], int | None]
    can_accept_fn: Callable[[str], bool]
    reserved_route_occupancy: Mapping[str, int] | None = None
    unconstrained: bool = False


class BaselineDispatchPolicy:
    """Baseline Dispatch Policy for assigning Transport Orders to vehicles and routes.

    Chooses a shortest admissible route and the nearest available suitable vehicle
    (accounting for vehicle speed multipliers) with deterministic tie-breaking.
    """

    def select_dispatch(
        self,
        order: TransportOrder | DispatchContext,
        candidate_routes: Sequence[RouteConfig] | None = None,
        available_vehicles: Sequence[Vehicle] | None = None,
        active_route_occupancy: Mapping[str, int] | None = None,
        node_distance_fn: Callable[[str, str], int | None] | None = None,
        can_accept_fn: Callable[[str], bool] | None = None,
        unconstrained: bool = False,
        reserved_route_occupancy: Mapping[str, int] | None = None,
        **kwargs: object,
    ) -> DispatchDecision | None:
        if isinstance(order, DispatchContext):
            ctx = order
            target_order = ctx.order
            routes = ctx.candidate_routes
            vehicles = ctx.available_vehicles
            occ = ctx.active_route_occupancy
            res_occ = ctx.reserved_route_occupancy
            dist_fn = ctx.node_distance_fn
            accept_fn = ctx.can_accept_fn
            is_unconstrained = ctx.unconstrained
        else:
            target_order = order
            assert candidate_routes is not None
            assert available_vehicles is not None
            assert active_route_occupancy is not None
            assert node_distance_fn is not None
            assert can_accept_fn is not None
            routes = candidate_routes
            vehicles = available_vehicles
            occ = active_route_occupancy
            res_occ = reserved_route_occupancy
            dist_fn = node_distance_fn
            accept_fn = can_accept_fn
            is_unconstrained = unconstrained

        # 1. Filter admissible routes
        admissible_routes: list[RouteConfig] = []
        for r in routes:
            if not accept_fn(r.target_node_id):
                continue
            if r.capacity is not None:
                current_occ = occ.get(r.id, 0)
                if res_occ is not None:
                    current_occ += res_occ.get(r.id, 0)
                if current_occ >= r.capacity:
                    continue
            admissible_routes.append(r)

        if not admissible_routes:
            return None

        # 2. Match suitable vehicles
        if is_unconstrained:
            # If no vehicles are configured in the simulation, return shortest admissible route
            # Deterministic tie-breaking: transit_time_ns, then route.id
            sorted_routes = sorted(
                admissible_routes,
                key=lambda r: (r.transit_time_ns, r.id),
            )
            best_route = sorted_routes[0]
            return DispatchDecision(
                order=target_order,
                route=best_route,
                vehicle=None,
                pickup_distance_ns=0,
            )

        if not vehicles:
            return None

        # For each admissible route, find available suitable vehicles
        candidates: list[tuple[int, int, str, str, RouteConfig, Vehicle, int]] = []

        for r in admissible_routes:
            for v in vehicles:
                if not v.is_available():
                    continue
                if r.pool_id is not None and v.pool_id != r.pool_id:
                    continue
                if r.required_capabilities:
                    if not set(r.required_capabilities).issubset(set(v.capabilities)):
                        continue

                dist = dist_fn(v.location, target_order.source_node_id)
                if dist is None:
                    # Vehicle cannot reach pickup node via directed material flow
                    continue

                effective_pickup_time = (
                    int(round(dist / v.speed_multiplier))
                    if v.speed_multiplier > 0
                    else dist
                )

                candidates.append((
                    r.transit_time_ns,
                    effective_pickup_time,
                    r.id,
                    v.id,
                    r,
                    v,
                    dist,
                ))

        if not candidates:
            return None

        # Shortest admissible route first (transit_time_ns), nearest suitable vehicle
        # (effective_pickup_time considering speed), deterministic tie-breaking on route.id, vehicle.id
        candidates.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
        best_candidate = candidates[0]
        return DispatchDecision(
            order=target_order,
            route=best_candidate[4],
            vehicle=best_candidate[5],
            pickup_distance_ns=best_candidate[6],
        )
