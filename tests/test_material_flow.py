import pytest
from industrialsim.material_flow import (
    MaterialFlowGraph,
    Port,
    PortDirection,
    SourceNode,
    SinkNode,
    StationNode,
    BufferNode,
    Route,
)


def test_material_flow_graph_valid_linear_flow() -> None:
    graph = MaterialFlowGraph()

    src = SourceNode(
        id="src-1",
        output_ports=[Port(id="p-out", port_type="sedan_body", direction=PortDirection.OUTPUT)],
    )
    st1 = StationNode(
        id="st-1",
        input_ports=[Port(id="p-in", port_type="sedan_body", direction=PortDirection.INPUT)],
        output_ports=[Port(id="p-out", port_type="sedan_body", direction=PortDirection.OUTPUT)],
    )
    buf = BufferNode(
        id="buf-1",
        capacity=2,
        input_ports=[Port(id="p-in", port_type="sedan_body", direction=PortDirection.INPUT)],
        output_ports=[Port(id="p-out", port_type="sedan_body", direction=PortDirection.OUTPUT)],
    )
    snk = SinkNode(
        id="snk-1",
        input_ports=[Port(id="p-in", port_type="sedan_body", direction=PortDirection.INPUT)],
    )

    graph.add_node(src)
    graph.add_node(st1)
    graph.add_node(buf)
    graph.add_node(snk)

    graph.add_route(Route(id="r1", source_node_id="src-1", source_port_id="p-out", target_node_id="st-1", target_port_id="p-in"))
    graph.add_route(Route(id="r2", source_node_id="st-1", source_port_id="p-out", target_node_id="buf-1", target_port_id="p-in"))
    graph.add_route(Route(id="r3", source_node_id="buf-1", source_port_id="p-out", target_node_id="snk-1", target_port_id="p-in"))

    errors = graph.validate()
    assert errors == []


def test_material_flow_rejects_incompatible_ports() -> None:
    graph = MaterialFlowGraph()
    src = SourceNode(
        id="src-1",
        output_ports=[Port(id="p-out", port_type="suv_body", direction=PortDirection.OUTPUT)],
    )
    st1 = StationNode(
        id="st-1",
        input_ports=[Port(id="p-in", port_type="sedan_body", direction=PortDirection.INPUT)],
        output_ports=[],
    )
    graph.add_node(src)
    graph.add_node(st1)
    graph.add_route(Route(id="r1", source_node_id="src-1", source_port_id="p-out", target_node_id="st-1", target_port_id="p-in"))

    errors = graph.validate()
    assert any("incompatible port type" in err.lower() for err in errors)


def test_material_flow_rejects_unreachable_sink() -> None:
    graph = MaterialFlowGraph()
    src = SourceNode(
        id="src-1",
        output_ports=[Port(id="p-out", port_type="sedan_body", direction=PortDirection.OUTPUT)],
    )
    snk = SinkNode(
        id="snk-1",
        input_ports=[Port(id="p-in", port_type="sedan_body", direction=PortDirection.INPUT)],
    )
    graph.add_node(src)
    graph.add_node(snk)
    # No route connecting src to snk

    errors = graph.validate()
    assert any("unreachable" in err.lower() for err in errors)


def test_material_flow_allows_cycles_and_parallel_routes() -> None:
    graph = MaterialFlowGraph()
    src = SourceNode(
        id="src-1",
        output_ports=[Port(id="p-out", port_type="sedan_body", direction=PortDirection.OUTPUT)],
    )
    st1 = StationNode(
        id="st-1",
        input_ports=[
            Port(id="p-in", port_type="sedan_body", direction=PortDirection.INPUT),
            Port(id="p-rework-in", port_type="sedan_body", direction=PortDirection.INPUT),
        ],
        output_ports=[
            Port(id="p-out-primary", port_type="sedan_body", direction=PortDirection.OUTPUT),
            Port(id="p-out-rework", port_type="sedan_body", direction=PortDirection.OUTPUT),
        ],
    )
    snk = SinkNode(
        id="snk-1",
        input_ports=[Port(id="p-in", port_type="sedan_body", direction=PortDirection.INPUT)],
    )
    graph.add_node(src)
    graph.add_node(st1)
    graph.add_node(snk)

    # Parallel routes from src to st-1
    graph.add_route(Route(id="r-main", source_node_id="src-1", source_port_id="p-out", target_node_id="st-1", target_port_id="p-in"))
    graph.add_route(Route(id="r-alt", source_node_id="src-1", source_port_id="p-out", target_node_id="st-1", target_port_id="p-in"))

    # Cycle: st-1 rework port back to st-1 rework in
    graph.add_route(Route(id="r-rework", source_node_id="st-1", source_port_id="p-out-rework", target_node_id="st-1", target_port_id="p-rework-in"))

    # Exit route to sink
    graph.add_route(Route(id="r-exit", source_node_id="st-1", source_port_id="p-out-primary", target_node_id="snk-1", target_port_id="p-in"))

    errors = graph.validate()
    assert errors == []
