"""Live transport projections use the scheduled arrival, without advancing the engine."""
import pytest

from industrialsim.application import EpisodeSession
from industrialsim.decisions import BaselineDecisionProvider


@pytest.mark.parametrize('with_vehicle, arrival_ns', [(False, '10000000000'), (True, '5000000000')])
def test_transport_observation_and_checkpoint(with_vehicle: bool, arrival_ns: str) -> None:
    model = {
        'episode': {'end_condition': {'type': 'all_units_terminal'}},
        'production_units': [{'id': 'unit', 'variant': 'part', 'source_id': 'source'}],
        'material_flow': {
            'nodes': [
                {'id': 'source', 'kind': 'source', 'output_ports': [{'id': 'out', 'direction': 'output', 'port_type': 'part'}]},
                {'id': 'destination', 'kind': 'sink', 'input_ports': [{'id': 'in', 'direction': 'input', 'port_type': 'part'}]},
            ],
            'routes': [
                {'id': route, 'source_node_id': 'source', 'source_port_id': 'out',
                 'target_node_id': 'destination', 'target_port_id': 'in', 'transit_time': duration}
                for route, duration in [('slow', '20s'), ('chosen', '10s')]
            ],
        },
        **({'vehicles': [{'id': 'vehicle', 'initial_location': 'source', 'speed_multiplier': 2}]} if with_vehicle else {}),
    }
    session = EpisodeSession(model, decision_provider=BaselineDecisionProvider())
    restored = None
    try:
        session.advance(until_time_ns=1_000_000_000)
        checkpoint = session.create_checkpoint()
        observation = session.observe()
        assert len(observation['transports']) == 1
        transport = next(iter(observation['transports'].values()))
        assert transport == {
            'id': transport['id'], 'unit_id': 'unit', 'route_id': 'chosen',
            'source_node_id': 'source', 'target_node_id': 'destination',
            'pickup_time_ns': '0', 'arrival_time_ns': arrival_ns,
        }
        assert session.observation_views()['truth']['transports'] == observation['transports']
        assert 'transports' not in session.observation_views()['available']
        observation['transports'].clear()
        assert len(session.observe()['transports']) == 1
        assert session.create_checkpoint() == checkpoint
        restored = EpisodeSession.from_checkpoint(checkpoint, decision_provider=BaselineDecisionProvider())
        assert restored.observe()['transports'] == session.observe()['transports']
        restored.advance()
        session.advance()
        assert restored.observe()['transports'] == session.observe()['transports'] == {}
    finally:
        if restored:
            restored.close()
        session.close()
