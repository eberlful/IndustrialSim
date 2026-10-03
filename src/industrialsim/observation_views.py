"""Presentation projections of existing Decision Requests, never provider input."""
from copy import deepcopy
from typing import Any


def available_observations(truth: dict[str, Any], requests: list[dict[str, Any]]) -> dict[str, Any]:
    """Mark absent values explicitly; preserve the complete request contracts.

    Static topology and entity identifiers are workspace context. Dynamic values
    come exclusively from the current requests, with no last-batch fallback.
    """
    available: dict[str, Any] = {
        'simulated_time_ns': truth['simulated_time_ns'],
        'graph': deepcopy(truth['graph']), 'plant': deepcopy(truth['plant']),
        'requests': deepcopy(requests), 'raw_metrics': {}, 'production_units': {},
    }
    for kind in ('stations', 'buffers', 'machines', 'workers'):
        available[kind] = {
            identifier: {field: identifier if field == 'id' else None for field in entity}
            for identifier, entity in truth[kind].items()
        }
    for request in requests:
        observation = request['observation']
        machine_id = observation.get('machine_id')
        if machine_id in available['machines']:
            machine = available['machines'][machine_id]
            for field, source in (('health', 'health'), ('operating_mode', 'operating_mode'),
                                  ('failed', 'is_failed'), ('in_maintenance', 'is_in_maintenance')):
                if source in observation:
                    machine[field] = deepcopy(observation[source])
        buffer_id = observation.get('buffer_id')
        if buffer_id in available['buffers']:
            buffer = available['buffers'][buffer_id]
            for field in ('capacity', 'occupancy'):
                if field in observation:
                    buffer[field] = observation[field]
            if 'occupants' in observation:
                buffer['unit_ids'] = [unit['unit_id'] for unit in observation['occupants']]
                for unit in observation['occupants']:
                    available['production_units'][unit['unit_id']] = {
                        'id': unit['unit_id'], 'variant': unit['variant'],
                        'location': buffer_id, 'quality_state': None, 'state': None,
                        'process_step_index': None, 'findings': None,
                    }
        unit_id = observation.get('unit_id')
        if unit_id:
            unit = available['production_units'].setdefault(unit_id, {
                'id': unit_id, 'variant': None, 'location': None, 'state': None,
                'quality_state': None, 'process_step_index': None, 'findings': None,
            })
            if 'variant' in observation:
                unit['variant'] = observation['variant']
            if 'current_node_id' in observation:
                location = observation['current_node_id']
                unit['location'] = location
                node = available['stations'].get(location) or available['buffers'].get(location)
                if node is not None:
                    observed = node.setdefault('observed_unit_ids', [])
                    if unit_id not in observed:
                        observed.append(unit_id)
    return available
