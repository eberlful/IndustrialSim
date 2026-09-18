from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Sequence


class PortDirection(StrEnum):
    INPUT = "input"
    OUTPUT = "output"


@dataclass(frozen=True)
class Port:
    id: str
    port_type: str
    direction: PortDirection


class NodeKind(StrEnum):
    SOURCE = "source"
    SINK = "sink"
    STATION = "station"
    BUFFER = "buffer"


@dataclass
class MaterialFlowNode:
    id: str
    kind: NodeKind
    input_ports: dict[str, Port] = field(default_factory=dict)
    output_ports: dict[str, Port] = field(default_factory=dict)
    hall_id: str | None = None

    def get_port(self, port_id: str) -> Port | None:
        return self.input_ports.get(port_id) or self.output_ports.get(port_id)


class SourceNode(MaterialFlowNode):
    def __init__(
        self,
        id: str,
        output_ports: Sequence[Port],
        hall_id: str | None = None,
    ) -> None:
        super().__init__(
            id=id,
            kind=NodeKind.SOURCE,
            input_ports={},
            output_ports={p.id: p for p in output_ports},
            hall_id=hall_id,
        )


class SinkNode(MaterialFlowNode):
    def __init__(
        self,
        id: str,
        input_ports: Sequence[Port],
        hall_id: str | None = None,
    ) -> None:
        super().__init__(
            id=id,
            kind=NodeKind.SINK,
            input_ports={p.id: p for p in input_ports},
            output_ports={},
            hall_id=hall_id,
        )


class StationNode(MaterialFlowNode):
    def __init__(
        self,
        id: str,
        input_ports: Sequence[Port],
        output_ports: Sequence[Port],
        output_capacity: int = 0,
        hall_id: str | None = None,
    ) -> None:
        super().__init__(
            id=id,
            kind=NodeKind.STATION,
            input_ports={p.id: p for p in input_ports},
            output_ports={p.id: p for p in output_ports},
            hall_id=hall_id,
        )
        self.output_capacity = output_capacity


class BufferNode(MaterialFlowNode):
    def __init__(
        self,
        id: str,
        capacity: int,
        input_ports: Sequence[Port],
        output_ports: Sequence[Port],
        hall_id: str | None = None,
    ) -> None:
        super().__init__(
            id=id,
            kind=NodeKind.BUFFER,
            input_ports={p.id: p for p in input_ports},
            output_ports={p.id: p for p in output_ports},
            hall_id=hall_id,
        )
        if capacity < 1:
            raise ValueError(f"Buffer capacity must be >= 1, got {capacity}")
        self.capacity = capacity


@dataclass(frozen=True)
class Route:
    id: str
    source_node_id: str
    source_port_id: str
    target_node_id: str
    target_port_id: str
    transit_time_ns: int = 0


class MaterialFlowGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, MaterialFlowNode] = {}
        self.routes: dict[str, Route] = {}
        self._routes_by_source: dict[str, list[Route]] = {}
        self._routes_by_target: dict[str, list[Route]] = {}

    def add_node(self, node: MaterialFlowNode) -> None:
        if node.id in self.nodes:
            raise ValueError(f"Duplicate node ID: '{node.id}'")
        self.nodes[node.id] = node
        self._routes_by_source[node.id] = []
        self._routes_by_target[node.id] = []

    def add_route(self, route: Route) -> None:
        if route.id in self.routes:
            raise ValueError(f"Duplicate route ID: '{route.id}'")
        self.routes[route.id] = route
        self._routes_by_source.setdefault(route.source_node_id, []).append(route)
        self._routes_by_target.setdefault(route.target_node_id, []).append(route)

    def get_routes_from(self, node_id: str) -> list[Route]:
        return list(self._routes_by_source.get(node_id, []))

    def get_routes_to(self, node_id: str) -> list[Route]:
        return list(self._routes_by_target.get(node_id, []))

    def validate(self) -> list[str]:
        errors: list[str] = []

        sources = [n for n in self.nodes.values() if n.kind == NodeKind.SOURCE]
        sinks = [n for n in self.nodes.values() if n.kind == NodeKind.SINK]

        if not sources:
            errors.append("Material flow graph must define at least one Source node")
        if not sinks:
            errors.append("Material flow graph must define at least one Sink node")

        # Validate routes
        for route in self.routes.values():
            src_node = self.nodes.get(route.source_node_id)
            if not src_node:
                errors.append(f"Route '{route.id}' references unknown source node '{route.source_node_id}'")
                continue

            tgt_node = self.nodes.get(route.target_node_id)
            if not tgt_node:
                errors.append(f"Route '{route.id}' references unknown target node '{route.target_node_id}'")
                continue

            src_port = src_node.output_ports.get(route.source_port_id)
            if not src_port:
                errors.append(
                    f"Route '{route.id}' references non-existent output port '{route.source_port_id}' on node '{src_node.id}'"
                )

            tgt_port = tgt_node.input_ports.get(route.target_port_id)
            if not tgt_port:
                errors.append(
                    f"Route '{route.id}' references non-existent input port '{route.target_port_id}' on node '{tgt_node.id}'"
                )

            if src_port and tgt_port:
                if src_port.port_type != tgt_port.port_type:
                    errors.append(
                        f"Incompatible port types on route '{route.id}': "
                        f"{src_node.id}.{src_port.id} ({src_port.port_type}) -> "
                        f"{tgt_node.id}.{tgt_port.id} ({tgt_port.port_type})"
                    )

        if errors:
            return errors

        # Reachability validation
        # 1. Forward reachability from each source to at least one sink
        forward_adj: dict[str, list[str]] = {nid: [] for nid in self.nodes}
        for route in self.routes.values():
            forward_adj[route.source_node_id].append(route.target_node_id)

        for src in sources:
            visited: set[str] = set()
            queue = deque([src.id])
            reached_sink = False
            while queue:
                curr = queue.popleft()
                if curr in visited:
                    continue
                visited.add(curr)
                if self.nodes[curr].kind == NodeKind.SINK:
                    reached_sink = True
                    break
                for nxt in forward_adj.get(curr, []):
                    if nxt not in visited:
                        queue.append(nxt)
            if not reached_sink:
                errors.append(f"Source '{src.id}' cannot reach any sink node")

        # 2. Backward reachability: every sink must be reachable from at least one source
        backward_adj: dict[str, list[str]] = {nid: [] for nid in self.nodes}
        for route in self.routes.values():
            backward_adj[route.target_node_id].append(route.source_node_id)

        for snk in sinks:
            visited = set()
            queue = deque([snk.id])
            reached_source = False
            while queue:
                curr = queue.popleft()
                if curr in visited:
                    continue
                visited.add(curr)
                if self.nodes[curr].kind == NodeKind.SOURCE:
                    reached_source = True
                    break
                for prev in backward_adj.get(curr, []):
                    if prev not in visited:
                        queue.append(prev)
            if not reached_source:
                errors.append(f"Required sink '{snk.id}' is unreachable from any source")

        return errors
