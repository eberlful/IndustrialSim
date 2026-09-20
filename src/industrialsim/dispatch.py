from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from industrialsim.config import RouteConfig
from industrialsim.domain import ProductionUnit, TransportOrder, Vehicle


@dataclass(frozen=True)
class DispatchDecision:
    order: TransportOrder
    route: RouteConfig
    vehicle: Vehicle | None
    pickup_distance_ns: int = 0


class BaselineDispatchPolicy:
    """Baseline Dispatch Policy for assigning Transport Orders to vehicles and routes.

    Chooses the nearest available suitable vehicle and a shortest admissible route
    with deterministic tie-breaking.
    """

    def select_dispatch(
        self,
        order: TransportOrder,
        unit: ProductionUnit,
        candidate_routes: Sequence[RouteConfig],
        available_vehicles: Sequence[Vehicle],
        active_route_occupancy: Mapping[str, int],
        node_distance_fn: Callable[[str, str], int | None],
        can_accept_fn: Callable[[str], bool],
        unconstrained: bool = False,
    ) -> DispatchDecision | None:
        # 1. Filter admissible routes
        admissible_routes: list[RouteConfig] = []
        for r in candidate_routes:
            if not can_accept_fn(r.target_node_id):
                continue
            if r.capacity is not None:
                current_occ = active_route_occupancy.get(r.id, 0)
                if current_occ >= r.capacity:
                    continue
            admissible_routes.append(r)

        if not admissible_routes:
            return None

        # 2. Match suitable vehicles
        if unconstrained:
            # If no vehicles are configured in the simulation, return shortest admissible route
            # Deterministic tie-breaking: transit_time_ns, then route.id
            sorted_routes = sorted(
                admissible_routes,
                key=lambda r: (r.transit_time_ns, r.id),
            )
            best_route = sorted_routes[0]
            return DispatchDecision(
                order=order,
                route=best_route,
                vehicle=None,
                pickup_distance_ns=0,
            )

        if not available_vehicles:
            return None

        # For each admissible route, find available suitable vehicles
        candidates: list[tuple[int, int, str, str, RouteConfig, Vehicle]] = []

        for r in admissible_routes:
            for v in available_vehicles:
                if not v.is_available():
                    continue
                if r.pool_id is not None and v.pool_id != r.pool_id:
                    continue
                if r.required_capabilities:
                    if not set(r.required_capabilities).issubset(set(v.capabilities)):
                        continue

                dist = node_distance_fn(v.location, order.source_node_id)
                if dist is None:
                    # Vehicle cannot reach pickup node
                    continue

                candidates.append((
                    dist,
                    r.transit_time_ns,
                    r.id,
                    v.id,
                    r,
                    v,
                ))

        if not candidates:
            return None

        # Nearest available suitable vehicle (min dist), shortest admissible route (min transit_time_ns),
        # deterministic tie-breaking on route.id, vehicle.id
        candidates.sort(key=lambda c: (c[0], c[1], c[2], c[3]))
        best_candidate = candidates[0]
        return DispatchDecision(
            order=order,
            route=best_candidate[4],
            vehicle=best_candidate[5],
            pickup_distance_ns=best_candidate[0],
        )
