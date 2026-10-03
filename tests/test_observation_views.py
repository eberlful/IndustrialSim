"""Truth and provider observations through the public EpisodeSession seam."""
from industrialsim.application import EpisodeSession, run_episode
from industrialsim.decisions import BaselineDecisionProvider

MODEL = '''
episode: {end_condition: {type: max_time, max_time: 3s}}
production_plan: [{id: batch, variant: sedan, quantity: 1, release_time: 2s}]
stations: [{id: station, operations: [{id: op, duration: 1s}]}]
machines: [{id: machine, initial_health: 0.75}]
decision_triggers:
  - {id: safe, trigger_type: safe_point, target_id: station, times_ns: [0]}
'''


def test_available_observations_are_contract_faithful_and_reads_do_not_change_outcomes() -> None:
    session = EpisodeSession(MODEL, decision_provider=BaselineDecisionProvider())
    views = session.observation_views()
    assert views['truth']['machines']['machine']['health'] == 0.75
    assert views['available']['machines']['machine']['health'] is None
    assert views['available']['requests'] == []
    assert views['available']['raw_metrics'] == {}
    assert views['available']['production_units'] == {}
    session.advance_to_next_decision_batch()
    pending = session.decision_batch()
    before = session.snapshot()
    views = session.observation_views()
    assert views['available']['requests'] == pending['batch']['requests']
    assert views['available']['stations']['station']['occupancy'] is None
    assert views['available']['machines']['machine']['health'] is None
    views['available']['requests'][0]['observation']['available_workers'].append('fake')
    assert session.decision_batch() == pending
    assert session.snapshot() == before
    session.resolve_decision_batch()
    assert session.observation_views()['available']['requests'] == []
    session.advance()
    assert session.finalize().to_dict() == run_episode(MODEL, decision_provider=BaselineDecisionProvider()).to_dict()
    session.close()


def test_exact_machine_state_exposed_by_the_contract_remains_available() -> None:
    session = EpisodeSession(MODEL.replace('target_id: station', 'target_id: machine'))
    session.advance_to_next_decision_batch()
    views = session.observation_views()
    machine = views['available']['machines']['machine']
    assert machine['health'] == 0.75
    assert machine['operating_mode'] == 'nominal'
    assert machine['failed'] is False
    assert machine['in_maintenance'] is False
    assert machine['capacity'] is None
    assert machine['allocations'] is None
    assert views['available']['requests'][0]['observation']['physical_state'] == {'health': 0.75}
    session.close()


def test_service_snapshot_separates_truth_and_current_provider_payloads(tmp_path) -> None:
    import time
    from industrialsim.episode_worker import EpisodeWorker
    from industrialsim.local_service import browser_episode_response

    with EpisodeWorker(tmp_path) as worker:
        worker.start(MODEL.replace('target_id: station', 'target_id: machine'), mode='manual')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            episode = worker.snapshot()['episode']
            if episode['state'] == 'awaiting_decisions':
                break
            time.sleep(0.005)
        assert episode['state'] == 'awaiting_decisions'
        assert episode['observation_views']['truth']['machines']['machine']['capacity'] == 1
        assert episode['observation_views']['available']['machines']['machine']['capacity'] is None
        converted = browser_episode_response({'episode': episode})['episode']
        assert converted['observation_views']['available']['requests'] == converted['decision_batch']['batch']['requests']
        assert converted['observation_views']['available']['requests'][0]['observation']['health'] == 0.75
        assert 'capacity' not in converted['decision_batch']['batch']['requests'][0]['observation']


def test_buffer_contract_exposes_occupants_without_hidden_quality() -> None:
    model = {
        'episode': {'end_condition': {'type': 'all_units_terminal'}},
        'production_plan': [{'id': 'batch', 'variant': 'sedan', 'quantity': 2, 'source_id': 'source'}],
        'material_flow': {
            'nodes': [
                {'id': 'source', 'kind': 'source', 'output_ports': [{'id': 'out', 'port_type': 'part', 'direction': 'output'}]},
                {'id': 'buffer', 'kind': 'buffer', 'capacity': 3,
                 'input_ports': [{'id': 'in', 'port_type': 'part', 'direction': 'input'}],
                 'output_ports': [{'id': 'out', 'port_type': 'part', 'direction': 'output'}]},
                {'id': 'station', 'kind': 'station', 'operations': [{'id': 'op', 'duration': '10s'}],
                 'input_ports': [{'id': 'in', 'port_type': 'part', 'direction': 'input'}],
                 'output_ports': [{'id': 'out', 'port_type': 'part', 'direction': 'output'}]},
                {'id': 'sink', 'kind': 'sink', 'input_ports': [{'id': 'in', 'port_type': 'part', 'direction': 'input'}]},
            ],
            'routes': [{'id': f'{source}-{target}', 'source_node_id': source, 'target_node_id': target,
                        'source_port_id': 'out', 'target_port_id': 'in', 'transit_time': '0s'}
                       for source, target in [('source', 'buffer'), ('buffer', 'station'), ('station', 'sink')]],
        },
        'decision_triggers': [{'id': 'buffer-full', 'buffer_id': 'buffer', 'threshold': 1}],
    }
    session = EpisodeSession(model)
    session.advance_to_next_decision_batch()
    views = session.observation_views()
    buffer = views['available']['buffers']['buffer']
    assert buffer['capacity'] == 3
    assert buffer['occupancy'] == 1
    assert buffer['unit_ids'] == ['batch-1']
    unit = views['available']['production_units']['batch-1']
    assert unit['variant'] == 'sedan'
    assert unit['quality_state'] is None
    assert unit['findings'] is None
    assert views['available']['requests'] == session.decision_batch()['batch']['requests']
    session.close()
