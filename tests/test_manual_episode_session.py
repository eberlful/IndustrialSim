"""Manual Decision Batches through the public Episode session seam."""
from industrialsim.application import EpisodeSession, run_episode
from industrialsim.decisions import BaselineDecisionProvider

MODEL = '''
seed: 42
episode: {end_condition: {type: max_time, max_time: 3s}}
production_plan: [{id: batch, variant: sedan, quantity: 1, release_time: 2s}]
stations: [{id: station, operations: [{id: op, duration: 1s}]}]
decision_triggers:
  - {id: safe, trigger_type: safe_point, target_id: station, interval_ns: 1000000000, on_failure: abort}
'''


def test_manual_batch_rejection_correction_and_once_only_application() -> None:
    session = EpisodeSession(MODEL, decision_provider=BaselineDecisionProvider())
    session.advance_to_next_decision_batch()
    pending = session.decision_batch()
    assert pending is not None
    batch = pending['batch']
    assert len(batch['requests']) == 1
    assert all(request['time_ns'] == batch['time_ns'] for request in batch['requests'])
    before = session.observe()
    cursor = session.events()['next_cursor']
    rejected = session.submit_decision_batch(batch['batch_id'], [])
    assert not rejected['accepted']
    assert any(diagnostic['code'] == 'MISSING_ACTION' for diagnostic in rejected['diagnostics'])
    assert session.observe() == before
    assert session.events(cursor)['records'] == []
    assert session.decision_batch() == pending
    wrong = session.submit_decision_batch(batch['batch_id'], [
        {'action_type': 'reconfiguration', 'target_id': 'station', 'configuration': {}, 'duration_ns': -1}])
    assert not wrong['accepted']
    action = {'action_type': 'reconfiguration', 'target_id': 'station', 'configuration': {'cycle_time_multiplier': 1.1}}
    accepted = session.submit_decision_batch(batch['batch_id'], [action])
    assert accepted['accepted'], accepted
    assert str(session.snapshot().simulated_time_ns) == before['simulated_time_ns']
    assert session.decision_batch() is None
    assert not session.submit_decision_batch(batch['batch_id'], [action])['accepted']
    records = session.events(cursor)['records']
    assert sum(record['event_type'] == 'decision_action' for record in records) == 1
    assert next(record for record in records if record['event_type'] == 'decision_action')['provenance']['provider_id'] == 'manual'
    session.close()


def test_complete_shared_batch_is_atomic_and_stale_response_cannot_answer_next_batch() -> None:
    model = MODEL.replace('stations: [{id: station,', 'stations: [{id: station,') + '''
workers: [{id: worker}]
'''
    model = model.replace('decision_triggers:', 'decision_triggers:\n  - {id: worker-safe, trigger_type: safe_point, target_id: worker, interval_ns: 1000000000}')
    session = EpisodeSession(model)
    session.advance_to_next_decision_batch()
    pending = session.decision_batch()
    assert pending is not None
    batch = pending['batch']
    assert {request['target_id'] for request in batch['requests']} == {'station', 'worker'}
    assert {request['observation']['aggregate_metrics']['simulation_time_ns'] for request in batch['requests']} == {batch['time_ns']}
    proposal = [
        {'action_type': 'reconfiguration', 'target_id': 'station', 'configuration': {'cycle_time_multiplier': .5}, 'cost': 5},
        {'action_type': 'worker_reassignment', 'target_id': 'worker', 'assigned_station_id': 'missing'},
    ]
    before = session.snapshot()
    assert not session.submit_decision_batch(batch['batch_id'], proposal)['accepted']
    assert session.snapshot() == before
    assert session.observe()['workers']['worker']['allocations'] == []
    proposal[1]['assigned_station_id'] = 'station'
    assert session.submit_decision_batch(batch['batch_id'], proposal)['accepted']
    assert session.observe()['workers']['worker']['assigned_station_id'] == 'station'
    assert len(session.snapshot().decision_batches) == 1
    assert session.snapshot().decision_batches[0]['status'] == 'applied'
    session.advance_to_next_decision_batch()
    next_pending = session.decision_batch()
    assert next_pending is not None
    assert next_pending['batch']['batch_id'] != batch['batch_id']
    assert not session.submit_decision_batch(batch['batch_id'], proposal)['accepted']
    assert session.decision_batch() == next_pending
    session.close()


def test_schema_forms_expose_every_action_contract_and_reject_wrong_schema() -> None:
    from industrialsim.decisions import decision_action_schemas
    schemas = decision_action_schemas()
    assert set(schemas) == {'buffer_reorder', 'routing', 'dispatch', 'machine_mode', 'maintenance',
                            'reconfiguration', 'worker_reassignment', 'quality_control'}
    for action_type, schema in schemas.items():
        assert schema['properties']['action_type']['const'] == action_type
        assert schema['additionalProperties'] is False
    session = EpisodeSession(MODEL)
    session.advance_to_next_decision_batch()
    pending = session.decision_batch()
    assert pending is not None
    rejected = session.submit_decision_batch(pending['batch']['batch_id'], [
        {'action_type': 'machine_mode', 'target_id': 'station', 'mode': 'nominal'}])
    assert not rejected['accepted']
    assert any(diagnostic['code'] == 'INVALID_ACTION_CHOICE' for diagnostic in rejected['diagnostics'])
    session.close()


def test_actual_provider_exception_honors_abort_while_rejected_form_does_not() -> None:
    from industrialsim.decisions import DecisionProvider
    class FailingProvider(DecisionProvider):
        def decide(self, batch):
            raise RuntimeError('provider unavailable')
    session = EpisodeSession(MODEL, decision_provider=FailingProvider())
    session.advance_to_next_decision_batch()
    pending = session.decision_batch()
    assert pending is not None
    assert not session.submit_decision_batch(pending['batch']['batch_id'], [])['accepted']
    assert not session.snapshot().is_aborted
    session.resolve_decision_batch()
    assert session.snapshot().is_aborted
    assert session.snapshot().decision_batches[0]['status'] == 'aborted'
    assert any('provider unavailable' in diagnostic['message'] for diagnostic in session.snapshot().decision_diagnostics)
    session.close()


def test_buffer_action_contract_rejects_missing_occupants_then_applies_exact_order() -> None:
    from test_production_control_actions_e2e import BASE_ACTIONS_YAML
    session = EpisodeSession(BASE_ACTIONS_YAML)
    session.advance_to_next_decision_batch()
    pending = session.decision_batch()
    assert pending is not None
    batch = pending['batch']
    request = batch['requests'][0]
    assert pending['action_types'][request['request_id']] == ['buffer_reorder']
    rejected = session.submit_decision_batch(batch['batch_id'], [
        {'action_type': 'buffer_reorder', 'target_id': request['target_id'], 'new_order': []}])
    assert not rejected['accepted']
    assert any(diagnostic['code'] == 'INVALID_OCCUPANT_SET' for diagnostic in rejected['diagnostics'])
    order = ['u-urg-1', 'u-std-2', 'u-std-1']
    assert session.submit_decision_batch(batch['batch_id'], [
        {'action_type': 'buffer_reorder', 'target_id': request['target_id'], 'new_order': order}])['accepted']
    session.advance()
    assert session.finalize().decision_batches[0]['actions'][0]['new_order'] == order
    session.close()


def test_machine_mode_and_maintenance_forms_reuse_the_observation_choices() -> None:
    model = MODEL.replace('target_id: station', 'target_id: machine') + '''
machines:
  - id: machine
    modes: {nominal: {name: nominal}, eco: {name: eco}}
    maintenance: {duration: 100ns, health_threshold: 0.1}
'''
    for action in [
        {'action_type': 'machine_mode', 'target_id': 'machine', 'mode': 'eco'},
        {'action_type': 'maintenance', 'target_id': 'machine', 'trigger_maintenance': True},
    ]:
        session = EpisodeSession(model)
        session.advance_to_next_decision_batch()
        pending = session.decision_batch()
        assert pending is not None
        request = pending['batch']['requests'][0]
        assert pending['action_types'][request['request_id']] == ['machine_mode', 'maintenance']
        rejected = session.submit_decision_batch(pending['batch']['batch_id'], [
            {'action_type': 'machine_mode', 'target_id': 'machine', 'mode': 'unsupported'}])
        assert not rejected['accepted']
        assert session.submit_decision_batch(pending['batch']['batch_id'], [action])['accepted']
        machine = session.observe()['machines']['machine']
        if action['action_type'] == 'machine_mode':
            assert machine['operating_mode'] == 'eco'
        else:
            assert machine['in_maintenance']
        session.close()


def test_routing_form_uses_the_requested_unit_and_admissible_routes() -> None:
    from test_transport_orders_simulation import VEHICLE_CONTENTION_YAML
    model = VEHICLE_CONTENTION_YAML + '''
decision_triggers:
  - {id: route-choice, trigger_type: routing_decision, node_id: src, on_failure: abort}
'''
    session = EpisodeSession(model)
    session.advance_to_next_decision_batch()
    pending = session.decision_batch()
    assert pending is not None
    request = pending['batch']['requests'][0]
    assert request['observation']['unit_id'] == 'u1'
    assert pending['action_types'][request['request_id']] == ['routing']
    rejected = session.submit_decision_batch(pending['batch']['batch_id'], [
        {'action_type': 'routing', 'target_id': request['target_id'], 'route_id': 'missing', 'unit_id': 'u1'}])
    assert not rejected['accepted']
    assert session.submit_decision_batch(pending['batch']['batch_id'], [
        {'action_type': 'routing', 'target_id': request['target_id'], 'route_id': 'r_src_st1', 'unit_id': 'u1'}])['accepted']
    session.close()


def test_dispatch_forms_validate_individual_choices_and_joint_vehicle_claims() -> None:
    model = {
        'episode': {'end_condition': {'type': 'all_units_terminal'}},
        'production_units': [{'id': 'u1', 'variant': 'sedan', 'source_id': 'src1'},
                             {'id': 'u2', 'variant': 'sedan', 'source_id': 'src2'}],
        'vehicles': [{'id': 'v1', 'initial_location': 'src1'}, {'id': 'v2', 'initial_location': 'src2'}],
        'material_flow': {
            'nodes': [{'id': source, 'kind': 'source', 'output_ports': [{'id': 'out', 'direction': 'output', 'port_type': 'body'}]}
                      for source in ['src1', 'src2']] + [{'id': 'sink', 'kind': 'sink', 'input_ports': [{'id': 'in', 'direction': 'input', 'port_type': 'body'}]}],
            'routes': [{'id': f'{source}-sink', 'source_node_id': source, 'source_port_id': 'out',
                        'target_node_id': 'sink', 'target_port_id': 'in', 'transit_time': '1s'} for source in ['src1', 'src2']],
        },
        'decision_triggers': [{'id': 'dispatch', 'trigger_type': 'dispatch_decision', 'on_failure': 'abort'}],
    }
    session = EpisodeSession(model)
    session.advance_to_next_decision_batch()
    pending = session.decision_batch()
    assert pending is not None
    requests = pending['batch']['requests']
    assert len(requests) == 2
    assert {request['observation']['unit_id'] for request in requests} == {'u1', 'u2'}
    proposal = [{'action_type': 'dispatch', 'target_id': request['target_id'],
                 'route_id': f"{request['observation']['source_node_id']}-sink", 'vehicle_id': 'v1'} for request in requests]
    rejected = session.submit_decision_batch(pending['batch']['batch_id'], proposal)
    assert not rejected['accepted']
    assert any(diagnostic['code'] == 'COMPETING_RESOURCE_CLAIMS' for diagnostic in rejected['diagnostics'])
    proposal[1]['vehicle_id'] = 'missing'
    assert not session.submit_decision_batch(pending['batch']['batch_id'], proposal)['accepted']
    proposal[1]['vehicle_id'] = 'v2'
    assert session.submit_decision_batch(pending['batch']['batch_id'], proposal)['accepted']
    session.advance()
    assert session.finalize().status == 'completed'
    session.close()


def test_quality_control_form_enforces_declared_bounds_before_applying() -> None:
    model = MODEL.replace('duration: 1s', 'duration: 1s, inspection: {sensitivity: 0.5, false_positive_rate: 0}')
    model = model.replace('on_failure: abort}', 'on_failure: abort, quality_bounds: {max_inspection_intensity: 0.8}}')
    session = EpisodeSession(model)
    session.advance_to_next_decision_batch()
    pending = session.decision_batch()
    assert pending is not None
    batch_id = pending['batch']['batch_id']
    proposal = [{'action_type': 'quality_control', 'target_id': 'station', 'inspection_intensity': .9}]
    assert not session.submit_decision_batch(batch_id, proposal)['accepted']
    proposal[0]['inspection_intensity'] = .75
    assert session.submit_decision_batch(batch_id, proposal)['accepted']
    assert session.snapshot().decision_batches[0]['actions'][0]['inspection_intensity'] == .75
    session.close()


def test_manual_execution_matches_the_same_provider_actions_and_lossless_artifacts(tmp_path) -> None:
    from test_production_control_actions_e2e import BASE_ACTIONS_YAML
    from industrialsim.decisions import DecisionProvider
    from industrialsim.audit import load_audit_log
    class ManualEquivalentProvider(DecisionProvider):
        def decide(self, batch):
            response = BaselineDecisionProvider().decide(batch)
            response.provenance.provider_id = 'manual'
            response.provenance.model_id = None
            return response
    session = EpisodeSession(BASE_ACTIONS_YAML, output_dir=tmp_path / 'manual')
    while not session.finished:
        session.advance_to_next_decision_batch()
        pending = session.decision_batch()
        if pending:
            assert session.submit_decision_batch(pending['batch']['batch_id'], pending['suggested_actions'])['accepted']
    result = session.finalize()
    direct = run_episode(BASE_ACTIONS_YAML, decision_provider=ManualEquivalentProvider(), output_dir=tmp_path / 'direct')
    assert result.to_dict() == direct.to_dict()
    assert [record.model_dump() for record in load_audit_log(tmp_path / 'manual')] == [
        record.model_dump() for record in load_audit_log(tmp_path / 'direct')]
    session.close()


def test_routing_and_dispatch_for_same_unit_must_choose_the_same_route() -> None:
    from industrialsim.application import validate_config
    from test_transport_orders_simulation import VEHICLE_CONTENTION_YAML
    config = validate_config(VEHICLE_CONTENTION_YAML).config
    assert config is not None
    model = config.model_dump(mode='json')
    model['material_flow']['routes'].append({**model['material_flow']['routes'][0], 'id': 'alternative'})
    model['decision_triggers'] = [
        {'id': 'route', 'trigger_type': 'routing_decision', 'node_id': 'src'},
        {'id': 'dispatch', 'trigger_type': 'dispatch_decision'},
    ]
    session = EpisodeSession(model)
    session.advance_to_next_decision_batch()
    pending = session.decision_batch()
    assert pending is not None
    by_type = {request['action_schema']: request for request in pending['batch']['requests']}
    proposal = [
        {'action_type': 'routing', 'target_id': by_type['routing']['target_id'], 'route_id': 'r_src_st1', 'unit_id': 'u1'},
        {'action_type': 'dispatch', 'target_id': by_type['dispatch']['target_id'], 'route_id': 'alternative', 'vehicle_id': 'v1'},
    ]
    rejected = session.submit_decision_batch(pending['batch']['batch_id'], proposal)
    assert not rejected['accepted']
    assert any(diagnostic['code'] == 'CONFLICTING_ROUTE_CHOICES' for diagnostic in rejected['diagnostics'])
    proposal[1]['route_id'] = 'r_src_st1'
    assert session.submit_decision_batch(pending['batch']['batch_id'], proposal)['accepted']
    session.close()


def test_dispatch_selected_vehicle_is_used_instead_of_baseline_preference() -> None:
    from industrialsim.application import validate_config
    from test_transport_orders_simulation import VEHICLE_CONTENTION_YAML
    config = validate_config(VEHICLE_CONTENTION_YAML).config
    assert config is not None
    model = config.model_dump(mode='json')
    model['production_units'] = [model['production_units'][0]]
    model['vehicles'].append({**model['vehicles'][0], 'id': 'v2'})
    model['decision_triggers'] = [{'id': 'dispatch', 'trigger_type': 'dispatch_decision'}]
    session = EpisodeSession(model)
    session.advance_to_next_decision_batch()
    pending = session.decision_batch()
    assert pending is not None
    request = pending['batch']['requests'][0]
    assert session.submit_decision_batch(pending['batch']['batch_id'], [
        {'action_type': 'dispatch', 'target_id': request['target_id'], 'route_id': 'r_src_st1', 'vehicle_id': 'v2'}])['accepted']
    dispatched = [record for record in session.events()['records'] if record['event_type'] == 'unit_lifecycle'
                  and record['details'].get('transition') == 'in_transport']
    assert dispatched[-1]['details']['vehicle_id'] == 'v2'
    session.close()


def test_reassigned_worker_snapshot_preserves_assignment_and_qualifications() -> None:
    from industrialsim.checkpoint import WorkerSnapshot
    from industrialsim.domain import Worker

    worker = Worker(id='worker', qualifications=['operator'])
    worker.assigned_station_id = 'station'
    snapshot = WorkerSnapshot.from_dict(worker.to_snapshot()).to_dict()
    restored = Worker(id='worker', qualifications=['original'])
    restored.restore_state(snapshot)
    assert restored.assigned_station_id == 'station'
    assert restored.qualifications == ['operator']


def test_joint_maintenance_and_worker_actions_apply_before_resource_allocation() -> None:
    model = MODEL.replace('target_id: station', 'target_id: machine').replace('interval_ns: 1000000000', 'times_ns: [0]') + '''
workers: [{id: worker, qualifications: [maintenance]}]
machines:
  - id: machine
    maintenance:
      duration: 100ns
      required_workers: [{qualification: maintenance, count: 1}]
'''
    model = model.replace('decision_triggers:', 'decision_triggers:\n  - {id: worker-safe, trigger_type: safe_point, target_id: worker, times_ns: [0]}')
    for maintenance_first in (True, False):
        session = EpisodeSession(model)
        session.advance_to_next_decision_batch()
        pending = session.decision_batch()
        assert pending is not None
        actions = [
            {'action_type': 'maintenance', 'target_id': 'machine', 'trigger_maintenance': True},
            {'action_type': 'worker_reassignment', 'target_id': 'worker', 'assigned_station_id': 'station'},
        ]
        if not maintenance_first:
            actions.reverse()
        result = session.submit_decision_batch(pending['batch']['batch_id'], actions)
        assert result['accepted'], result
        observation = session.observe()
        assert observation['workers']['worker']['assigned_station_id'] == 'station'
        assert observation['machines']['machine']['in_maintenance']
        assert observation['workers']['worker']['allocations']
        session.close()


def test_route_forms_reject_branches_outside_the_units_process_plan() -> None:
    from industrialsim.application import validate_config
    from test_transport_orders_simulation import VEHICLE_CONTENTION_YAML
    validation = validate_config(VEHICLE_CONTENTION_YAML)
    assert validation.config is not None
    model = validation.config.model_dump(mode='json')
    model['production_units'] = model['production_units'][:1]
    shortcut = dict(model['material_flow']['routes'][0])
    shortcut.update(id='shortcut', target_node_id='snk')
    model['material_flow']['routes'].append(shortcut)
    model['process_plans'] = [{'variant': 'sedan', 'steps': [{'operation_id': 'op1', 'compatible_stations': ['st1']}]}]
    for trigger_type, target in [('routing_decision', 'src'), ('dispatch_decision', 'dispatch')]:
        model['decision_triggers'] = [{'id': 'choice', 'trigger_type': trigger_type,
                                       **({'node_id': target} if trigger_type == 'routing_decision' else {})}]
        session = EpisodeSession(model)
        session.advance_to_next_decision_batch()
        pending = session.decision_batch()
        assert pending is not None
        request = pending['batch']['requests'][0]
        assert {route['route_id'] for route in request['observation']['candidate_routes']} == {'r_src_st1'}
        action = {'action_type': 'routing' if trigger_type == 'routing_decision' else 'dispatch',
                  'target_id': request['target_id'], 'route_id': 'shortcut'}
        if trigger_type == 'dispatch_decision':
            action['vehicle_id'] = 'v1'
        before = session.observe()
        assert not session.submit_decision_batch(pending['batch']['batch_id'], [action])['accepted']
        assert session.observe() == before
        action['route_id'] = 'r_src_st1'
        assert session.submit_decision_batch(pending['batch']['batch_id'], [action])['accepted']
        session.advance()
        assert session.finalize().status == 'completed'
        session.close()


def test_dispatch_rejects_unsuitable_vehicle_without_consuming_the_batch() -> None:
    from industrialsim.application import validate_config
    from test_transport_orders_simulation import VEHICLE_CONTENTION_YAML
    validation = validate_config(VEHICLE_CONTENTION_YAML)
    assert validation.config is not None
    for constraint in ('capability', 'pool', 'reachability'):
        model = validation.config.model_dump(mode='json')
        model['production_units'] = model['production_units'][:1]
        model['vehicle_pools'] = [{'id': 'heavy-pool'}]
        model['vehicles'].append({**model['vehicles'][0], 'id': 'v2', 'capabilities': ['heavy'], 'pool_id': 'heavy-pool'})
        if constraint == 'capability':
            model['material_flow']['routes'][0]['required_capabilities'] = ['heavy']
        elif constraint == 'pool':
            model['material_flow']['routes'][0]['pool_id'] = 'heavy-pool'
        else:
            model['material_flow']['nodes'].append({'id': 'island', 'kind': 'sink',
                                                   'input_ports': [{'id': 'in', 'port_type': 'body', 'direction': 'input'}]})
            model['material_flow']['nodes'].append({'id': 'island-source', 'kind': 'source',
                                                   'output_ports': [{'id': 'out', 'port_type': 'body', 'direction': 'output'}]})
            model['material_flow']['routes'].append({'id': 'island-route', 'source_node_id': 'island-source',
                                                    'source_port_id': 'out', 'target_node_id': 'island',
                                                    'target_port_id': 'in', 'transit_time': 1})
            model['vehicles'][0]['initial_location'] = 'island'
        model['decision_triggers'] = [{'id': 'dispatch', 'trigger_type': 'dispatch_decision'}]
        session = EpisodeSession(model)
        session.advance_to_next_decision_batch()
        pending = session.decision_batch()
        assert pending is not None
        request = pending['batch']['requests'][0]
        assert next(vehicle for vehicle in request['observation']['available_vehicles'] if vehicle['vehicle_id'] == 'v2')['capabilities'] == ['heavy']
        action = {'action_type': 'dispatch', 'target_id': request['target_id'], 'route_id': 'r_src_st1', 'vehicle_id': 'v1'}
        before = session.observe()
        result = session.submit_decision_batch(pending['batch']['batch_id'], [action])
        assert not result['accepted'], (constraint, result)
        assert session.observe() == before
        assert session.decision_batch() == pending
        action['vehicle_id'] = 'v2'
        assert session.submit_decision_batch(pending['batch']['batch_id'], [action])['accepted']
        session.close()
