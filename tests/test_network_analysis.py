from concurrent.futures import CancelledError
import unittest

from vredefort.data import Road
from vredefort.live_traffic import AnalysisCancel
from vredefort.network_analysis import network_facts
from agent_fixture import fixture_network


def add_road(network, edge_id, source, target, length):
    path = (network.nodes_by_id[source]['point'], network.nodes_by_id[target]['point'])
    xs, ys = zip(*path)
    road = Road(edge_id, {'source': source, 'target': target, 'length_m': length, 'names': []},
                (path,), (min(xs), min(ys), max(xs), max(ys)))
    network.roads.append(road)
    network.roads_by_id[edge_id] = road
    for node in (source, target):
        network.edge_ids[node].append(edge_id)
        network.nodes_by_id[node]['degree'] += 1


class NetworkAnalysisTests(unittest.TestCase):
    def test_chain_bridge_and_articulation_are_dataset_facts(self):
        facts = network_facts(fixture_network(), 'e0', AnalysisCancel())
        alternative = facts['alternative_connection_without_selected_edge']
        self.assertTrue(alternative['selected_edge_is_bridge_in_dataset'])
        self.assertIsNone(alternative['length_m'])
        self.assertFalse(facts['junctions'][0]['is_articulation_in_dataset'])
        self.assertTrue(facts['junctions'][1]['is_articulation_in_dataset'])
        self.assertEqual(facts['junctions'][1]['neighbour_groups'], [['n0'], ['n2']])
        self.assertIn('not a verified drivable', alternative['interpretation'])
        self.assertIn('signal phases/timings', facts['unavailable_design_data'])

    def test_cycle_has_alternative_connection_without_articulation(self):
        network = fixture_network()
        add_road(network, 'e2', 'n0', 'n2', 300)
        facts = network_facts(network, 'e0', AnalysisCancel())
        alternative = facts['alternative_connection_without_selected_edge']
        self.assertEqual(alternative['edge_ids'], ['e2', 'e1'])
        self.assertEqual(alternative['length_m'], 408)
        self.assertFalse(alternative['selected_edge_is_bridge_in_dataset'])
        self.assertFalse(any(node['is_articulation_in_dataset'] for node in facts['junctions']))

    def test_parallel_edge_is_preserved_and_shortest_path_selected(self):
        network = fixture_network()
        add_road(network, 'e2', 'n0', 'n2', 300)
        add_road(network, 'parallel', 'n0', 'n1', 50)
        alternative = network_facts(network, 'e0', AnalysisCancel())['alternative_connection_without_selected_edge']
        self.assertEqual(alternative['edge_ids'], ['parallel'])
        self.assertEqual(alternative['length_m'], 50)

    def test_network_computation_obeys_cancellation(self):
        cancel = AnalysisCancel()
        cancel.set()
        with self.assertRaises(CancelledError):
            network_facts(fixture_network(), 'e0', cancel)


if __name__ == '__main__':
    unittest.main()
