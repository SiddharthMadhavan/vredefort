import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from citycollapse.analysis_scope import (AnalysisScope, MAX_AREA_ROADS, MAX_AREA_SAMPLES,
                                        connected_roads, scope_roads, selection_target, selection_roads)
from citycollapse.data import Road
from citycollapse.historical_traffic import HistoricalDataset
from citycollapse.live_traffic import AnalysisCancel, road_context, sample_road
from citycollapse.network_analysis import network_facts
from citycollapse.traffic_agents import TrafficAnalysts
from agent_fixture import fixture_network, fixture_server
from history_fixture import write_history
from test_network_analysis import add_road


class ScopeTests(unittest.TestCase):
    def test_junction_samples_every_approach_from_the_selected_node(self):
        network = fixture_network()
        scope = AnalysisScope.junction('n1')
        context = road_context(network, scope)
        self.assertNotIn('selected_road', context)
        self.assertEqual(context['selected_area']['selected_junction_id'], 'n1')
        self.assertEqual(context['selected_area']['edge_ids'], ['e0', 'e1'])
        self.assertTrue(all(item['node_point'] == network.nodes_by_id['n1']['point'] for item in context['samples']))
        self.assertTrue(all(sample_road(item['road'], item['node_point']) for item in context['samples']))

    def test_connected_area_deduplicates_shared_nodes_and_boundary_roads(self):
        network = fixture_network()
        add_road(network, 'e2', 'n0', 'n2', 300)
        scope = AnalysisScope.area(['e1', 'e0', 'e0'])
        context = road_context(network, scope)
        self.assertEqual(scope.identifiers, ('e0', 'e1'))
        self.assertEqual(context['selected_area']['total_length_m'], 216)
        self.assertEqual(context['selected_area']['node_count'], 3)
        self.assertEqual([item['edge_id'] for item in context['samples']], ['e0', 'e1', 'e2'])
        boundary = context['samples'][-1]
        self.assertEqual(boundary['scope_role'], 'boundary_approach')
        self.assertEqual(boundary['junctions'], ['Junction 1', 'Junction 3'])

    def test_disconnected_and_oversized_areas_rejected(self):
        network = fixture_network()
        network.nodes_by_id.update({'n3': {}, 'n4': {}})
        network.edge_ids.update({'n3': ['detached'], 'n4': ['detached']})
        network.roads_by_id['detached'] = Road('detached', {'source': 'n3', 'target': 'n4'}, (), ())
        for identifiers in ((), ('unknown',), ('e0', 'detached')):
            with self.assertRaises(ValueError):
                scope_roads(network, AnalysisScope.area(identifiers))
        network = fixture_network()
        for index in range(MAX_AREA_ROADS):
            add_road(network, f'parallel{index}', 'n0', 'n1', 50)
        with self.assertRaisesRegex(ValueError, 'at most'):
            scope_roads(network, AnalysisScope.area(network.roads_by_id))

    def test_removing_middle_edge_cannot_split_an_area(self):
        network = fixture_network()
        network.nodes_by_id['n3'] = {'point': network.nodes_by_id['n2']['point'], 'degree': 0}
        network.edge_ids['n3'] = []
        add_road(network, 'e2', 'n2', 'n3', 100)
        self.assertTrue(connected_roads(network, ['e0', 'e1', 'e2']))
        self.assertFalse(connected_roads(network, ['e0', 'e2']))

    def test_sample_limits_preserve_core_and_explicitly_list_omissions(self):
        network = fixture_network()
        for index in range(MAX_AREA_SAMPLES+4):
            add_road(network, f'parallel{index:02d}', 'n0', 'n1', 50)
        context = road_context(network, AnalysisScope.area(['e0']))
        self.assertEqual(len(context['samples']), MAX_AREA_SAMPLES)
        self.assertEqual(context['samples'][0]['edge_id'], 'e0')
        sampled = {item['edge_id'] for item in context['samples']}
        omitted = set(context['coverage']['omitted_boundary_edge_ids'])
        self.assertTrue(omitted)
        self.assertFalse(sampled & omitted)
        self.assertEqual(sampled | omitted, network.roads_by_id.keys())

    def test_scope_identity_is_stable_and_node_rendering_uses_all_arms(self):
        self.assertEqual(selection_target(('area', ('e1', 'e0'))), AnalysisScope.area(['e0', 'e1']))
        self.assertEqual(selection_target(('road', 'e0')), 'e0')
        self.assertEqual(selection_roads(fixture_network(), ('node', 'n1')), {'e0', 'e1'})

    def test_area_graph_facts_cover_each_selected_road_and_shared_junction(self):
        network = fixture_network()
        facts = network_facts(network, AnalysisScope.area(['e0', 'e1']), AnalysisCancel())
        paths = facts['alternative_connections_without_each_selected_edge']
        self.assertEqual([path['edge_id'] for path in paths], ['e0', 'e1'])
        self.assertTrue(all(path['selected_edge_is_bridge_in_dataset'] for path in paths))
        self.assertTrue(next(node for node in facts['junctions'] if node['id'] == 'n1')['is_articulation_in_dataset'])
        self.assertTrue(facts['area_topology']['selected_graph_is_connected'])

    def test_five_agents_share_junction_and_area_scopes(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            history = write_history(folder/'history.csv')
            for scope in (AnalysisScope.junction('n1'), AnalysisScope.area(['e0', 'e1'])):
                with self.subTest(kind=scope.kind), fixture_server(chat_delay=.001) as (url, requests), \
                        patch('citycollapse.live_traffic.FLOW_URL', url+'/flow'):
                    pipeline = TrafficAnalysts({'model': 'fixture', 'tomtom_key': 'fixture-key',
                                                'ollama_url': url, 'history_csv': str(history)})
                    pipeline.historical.dataset = HistoricalDataset(history, folder/'cache')
                    events = []
                    reports = pipeline.analyze(fixture_network(), scope, AnalysisCancel(), lambda *event: events.append(event))
                self.assertTrue(all(report['status'] == 'complete' for report in reports.values()))
                self.assertEqual(len([kind for kind, _ in requests if kind == 'GET']), 2)
                prompts = [json.loads(body['messages'][1]['content']) for kind, body in requests if kind == 'POST']
                self.assertTrue(all(body['options']['num_ctx'] == 16384 for kind, body in requests if kind == 'POST'))
                self.assertEqual(len(prompts), 5)
                self.assertTrue(all(payload['selected_area']['type'] == scope.kind for payload in prompts))
                self.assertTrue(all(payload['selected_area']['edge_ids'] == ['e0', 'e1'] for payload in prompts))
                self.assertTrue(all('selected_road' not in payload for payload in prompts))
                self.assertEqual(prompts[0]['unique_available_provider_fragments'], 1)
                self.assertTrue(prompts[1]['synthetic'])
                for payload in prompts[2:]:
                    self.assertEqual(payload['traffic_evidence']['live']['unique_available_provider_fragments'], 1)
                    self.assertEqual([row['scope_role'] for row in payload['traffic_evidence']['live']['observations']], ['selected', 'selected'])
                    self.assertNotIn('fixture-key', json.dumps(payload))

    def test_invalid_scope_starts_no_agent_work(self):
        pipeline = TrafficAnalysts({'model': 'fixture', 'tomtom_key': '', 'ollama_url': 'http://127.0.0.1:1'})
        events = []
        with self.assertRaises(ValueError):
            pipeline.analyze(fixture_network(), AnalysisScope.area(['unknown']), AnalysisCancel(), lambda *event: events.append(event))
        self.assertFalse(events)
