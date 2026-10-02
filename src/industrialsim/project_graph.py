"""Editable graph shape and completeness diagnostics for project drafts.

The simulation validator remains authoritative for schema/domain rules. These
checks keep incomplete graphs renderable and expose references even when a
schema error prevents the validator from reaching later configuration sections.
"""
from typing import Any

from industrialsim.config import PortConfig


def check_graph_shape(draft: dict[str, Any]) -> None:
    flow = draft.get('material_flow')
    if flow is None:
        return
    if not isinstance(flow, dict):
        raise ValueError('material_flow must be a mapping')
    for collection in ('nodes', 'routes'):
        elements = flow.get(collection, [])
        if not isinstance(elements, list):
            raise ValueError(f'material_flow.{collection} must be a list')
        ids: set[str] = set()
        for element in elements:
            if not isinstance(element, dict) or not isinstance(element.get('id'), str) or not element['id'].strip():
                raise ValueError(f'Each {collection} element requires a nonempty ID')
            if element['id'] in ids:
                raise ValueError(f'Duplicate {collection} ID: {element["id"]}')
            ids.add(element['id'])
            if collection == 'nodes':
                if element.get('kind') not in ('source', 'sink', 'station', 'buffer'):
                    raise ValueError('Node kind must be source, sink, station or buffer')
                for field in ('input_ports', 'output_ports'):
                    ports = element.get(field, [])
                    if not isinstance(ports, list):
                        raise ValueError(f'{element["id"]}.{field} must be a list')
                    for port in ports:
                        PortConfig.model_validate(port)
                if not isinstance(element.get('operations', []), list) or any(
                    not isinstance(op, dict) or not isinstance(op.get('id'), str)
                    for op in element.get('operations', [])
                ):
                    raise ValueError('Operations must be mappings with IDs')
            elif any(not isinstance(element.get(field), str) for field in (
                'source_node_id', 'source_port_id', 'target_node_id', 'target_port_id'
            )):
                raise ValueError('Routes require source/target node and Port IDs')


def graph_diagnostics(draft: dict[str, Any]) -> list[str]:
    flow = draft.get('material_flow')
    if not flow:
        return []
    nodes = {node['id']: node for node in flow.get('nodes', [])}
    errors: list[str] = []
    forward: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    backward: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    for index, route in enumerate(flow.get('routes', [])):
        endpoints_valid = True
        for side, ports in (('source', 'output_ports'), ('target', 'input_ports')):
            node_id = route[f'{side}_node_id']
            prefix = f'material_flow.routes.{index} ({route["id"]})'
            if node_id not in nodes:
                errors.append(f'{prefix}.{side}_node_id: references missing node {node_id!r}')
                endpoints_valid = False
            elif route[f'{side}_port_id'] not in {p['id'] for p in nodes[node_id].get(ports, [])}:
                errors.append(f'{prefix}.{side}_port_id: references missing Port {route[f"{side}_port_id"]!r} on {node_id!r}')
                endpoints_valid = False
        if endpoints_valid:
            forward[route['source_node_id']].add(route['target_node_id'])
            backward[route['target_node_id']].add(route['source_node_id'])

    # Inspect explicit graph references without rewriting unrelated sections.
    references = [('production_units', 'source_id'), ('production_plan', 'source_id'),
                  ('vehicles', 'initial_location'), ('decision_triggers', 'node_id'),
                  ('decision_triggers', 'buffer_id')]
    for collection, field in references:
        for index, element in enumerate(draft.get(collection, [])):
            value = element.get(field)
            if value is not None and value not in nodes:
                errors.append(f'{collection}.{index}.{field}: references missing node {value!r}')
    stations = {node_id: node for node_id, node in nodes.items() if node['kind'] == 'station'}
    stations.update({station['id']: station for station in draft.get('stations', [])})
    for collection, elements in (('material_flow.nodes', flow.get('nodes', [])), ('stations', draft.get('stations', []))):
        for node_index, node in enumerate(elements):
            for operation_index, operation in enumerate(node.get('operations', [])):
                inspection = operation.get('inspection') or {}
                target = inspection.get('rework_station_id')
                if target is None:
                    continue
                prefix = f'{collection}.{node_index}.operations.{operation_index}.inspection'
                if target not in stations:
                    errors.append(f'{prefix}.rework_station_id: references missing Station {target!r}')
                elif inspection.get('rework_operation_id') is not None and inspection['rework_operation_id'] not in {
                    op['id'] for op in stations[target].get('operations', [])
                }:
                    errors.append(f'{prefix}.rework_operation_id: references missing Operation {inspection["rework_operation_id"]!r} on {target!r}')
    for plan_index, plan in enumerate(draft.get('process_plans', [])):
        for step_index, step in enumerate(plan.get('steps', [])):
            for station in step.get('compatible_stations', []):
                if station not in stations:
                    errors.append(f'process_plans.{plan_index}.steps.{step_index}.compatible_stations: references missing Station {station!r}')

    def reachable(starts: set[str], adjacency: dict[str, set[str]]) -> set[str]:
        seen: set[str] = set()
        pending = list(starts)
        while pending:
            node_id = pending.pop()
            if node_id not in seen:
                seen.add(node_id)
                pending.extend(adjacency[node_id] - seen)
        return seen

    from_sources = reachable({n['id'] for n in nodes.values() if n['kind'] == 'source'}, forward)
    to_sinks = reachable({n['id'] for n in nodes.values() if n['kind'] == 'sink'}, backward)
    for index, node in enumerate(flow.get('nodes', [])):
        prefix = f'material_flow.nodes.{index} ({node["id"]})'
        if node['id'] not in from_sources:
            errors.append(f'{prefix}: disconnected from all source nodes')
        if node['id'] not in to_sinks:
            errors.append(f'{prefix}: cannot reach any sink node')
    return errors
