from array import array
import math
import unittest
from concurrent.futures import CancelledError
from threading import Event
from citycollapse.data import DATA, load_json
from citycollapse.traffic import TrafficDataset, TrafficModel, FIELDS
from citycollapse.traffic_rendering import traffic_color
from citycollapse.simulation_data import load_simulation_data


def model_fixture(edges, volumes=None, capacity=100):
    """Tiny undirected networks with complete, synthetic hourly measurements."""
    nodes = sorted({node for _, a, b, _ in edges for node in (a, b)})
    graph = {'nodes': [{'id': node} for node in nodes], 'edges': [
        {'id': identifier, 'source': a, 'target': b, 'length_m': length}
        for identifier, a, b, length in edges]}
    volumes = volumes or [50] * len(edges)
    values = array('f', [v for q in volumes for v in (q, 36, 1, 20, 50)])
    dataset = TrafficDataset({'hours': ['2026-10-01 00:00:00'],
                              'edge_ids': [e[0] for e in edges],
                              'capacities_veh_h': [capacity] * len(edges)}, values)
    return TrafficModel(graph, dataset)


class TrafficTests(unittest.TestCase):
    def test_baseline_exact_and_capacity_cost_monotone(self):
        model = model_fixture([('ab', 'a', 'b', 100), ('ac', 'a', 'c', 100), ('cb', 'c', 'b', 100)])
        baseline = model.solve(0)
        for link in baseline.links.values():
            self.assertAlmostEqual(link.flow, 50)
            self.assertAlmostEqual(link.speed, 36)
            self.assertAlmostEqual(link.congestion, .2)
        scenario = model.solve(0, {'ab'})
        self.assertEqual(scenario.links['ab'].flow, 0)
        self.assertTrue(scenario.links['ab'].closed)
        self.assertEqual(scenario.links['ac'].flow, 100)
        self.assertEqual(scenario.links['cb'].flow, 100)
        self.assertLess(scenario.links['ac'].speed, 36)
        self.assertGreater(scenario.links['ac'].congestion, .2)
        self.assertEqual(scenario.affected_demand, scenario.rerouted_demand + scenario.unmet_demand)
        self.assertEqual(scenario.unmet_demand, 0)
        restored = model.solve(0)
        self.assertEqual(restored.links, baseline.links)

    def test_cut_bridge_reports_unmet_without_teleporting(self):
        model = model_fixture([('ab', 'a', 'b', 100), ('bc', 'b', 'c', 100)])
        result = model.solve(0, {'ab'})
        self.assertEqual(result.rerouted_demand, 0)
        self.assertEqual(result.unmet_demand, 50)
        self.assertEqual(result.links['bc'].flow, 50)

    def test_closed_self_loop_demand_is_not_erased(self):
        model = model_fixture([('loop', 'a', 'a', 100), ('ab', 'a', 'b', 100)])
        result = model.solve(0, {'loop'})
        self.assertEqual(result.affected_demand, 50)
        self.assertEqual(result.unmet_demand, 50)
        self.assertEqual(result.rerouted_demand, 0)
        self.assertEqual(result.links['loop'].flow, 0)
        self.assertEqual(result.links['ab'].flow, 50)

    def test_junction_diverts_and_removes_all_incident_edges(self):
        model = model_fixture([('aj', 'a', 'j', 100), ('jb', 'j', 'b', 100), ('ac', 'a', 'c', 100), ('cb', 'c', 'b', 100)])
        result = model.solve(0, blocked_nodes={'j'})
        self.assertEqual(result.links['aj'].flow, 0)
        self.assertEqual(result.links['jb'].flow, 0)
        self.assertEqual(result.links['ac'].flow, 100)
        self.assertEqual(result.rerouted_demand, 50)
        self.assertEqual(result.unmet_demand, 0)
        # Explicitly blocking an already incident edge must not count demand twice.
        duplicate = model.solve(0, {'aj'}, {'j'})
        self.assertEqual(duplicate, result)

    def test_unequal_junction_loads_and_adjacent_node_clusters(self):
        model = model_fixture([('aj', 'a', 'j', 100), ('jk', 'j', 'k', 100), ('kb', 'k', 'b', 100), ('ab', 'a', 'b', 200)], [100, 900, 60, 20])
        result = model.solve(0, blocked_nodes={'j', 'k'})
        self.assertEqual(result.affected_demand, 80)  # boundary/2, internal 900 is not new trips
        self.assertEqual(result.rerouted_demand, 60)
        self.assertEqual(result.unmet_demand, 20)
        self.assertEqual(result.links['ab'].flow, 80)
        isolated = model.solve(0, {'ab'}, {'j', 'k'})
        self.assertAlmostEqual(isolated.affected_demand, isolated.unmet_demand)
        self.assertEqual(isolated.rerouted_demand, 0)

    def test_capacity_aware_assignment_splits_parallel_routes(self):
        model = model_fixture([('ab', 'a', 'b', 100), ('detour1', 'a', 'b', 120), ('detour2', 'a', 'b', 130)], [300, 10, 10])
        result = model.solve(0, {'ab'}, max_iterations=100, tolerance=.02)
        self.assertGreater(result.links['detour1'].flow, 10)
        self.assertGreater(result.links['detour2'].flow, 10)
        self.assertAlmostEqual(sum(result.links[e].flow - 10 for e in ('detour1', 'detour2')), 300)
        self.assertTrue(result.converged)
        self.assertLessEqual(result.relative_gap, .02)
        approximate = model.solve(0, {'ab'}, max_iterations=1, tolerance=1e-8)
        self.assertFalse(approximate.converged)

    def test_validation_and_palette(self):
        model = model_fixture([('ab', 'a', 'b', 100)])
        for edges, nodes in [({'bad'}, set()), (set(), {'bad'})]:
            with self.assertRaises(ValueError):
                model.solve(0, edges, nodes)
        with self.assertRaises(ValueError):
            model.solve(1)
        self.assertEqual(traffic_color(0), (61, 215, 108))
        self.assertEqual(traffic_color(1), (248, 62, 66))

    def test_obsolete_scenario_can_be_cancelled(self):
        model = model_fixture([('ab', 'a', 'b', 100)])
        cancelled = Event()
        cancelled.set()
        with self.assertRaises(CancelledError):
            model.solve(0, {'ab'}, cancel_event=cancelled)


class ActualTrafficTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = TrafficDataset.load(DATA)
        _, cls.model = load_simulation_data()

    def test_actual_coverage_and_finite_capacities(self):
        d = self.dataset
        self.assertEqual(len(d.hours), 168)
        self.assertEqual(d.count, 4448)
        self.assertEqual(d.metadata['source_rows'], 747264)
        self.assertTrue(all(math.isfinite(c) and c > 0 for c in d.capacities))
        for hour in (0, 8, 17, 167):
            baseline = self.model.solve(hour)
            for identifier, row in zip(d.edge_ids, d.hour(hour)):
                link = baseline.links[identifier]
                self.assertAlmostEqual(link.flow, row[0])
                self.assertAlmostEqual(link.speed, row[1])
                self.assertAlmostEqual(link.congestion, row[3] / 100)

    def test_actual_road_and_junction_closures_conserve_demand(self):
        for edges, nodes in [({'kml_merged_e_6154_0_1'}, set()), (set(), {next(node for node, adjacent in self.model.adjacency.items() if len(adjacent) >= 3)})]:
            result = self.model.solve(8, edges, nodes)
            self.assertAlmostEqual(result.affected_demand, result.rerouted_demand + result.unmet_demand, places=6)
            self.assertTrue(all(math.isfinite(s.flow) and s.flow >= 0 and 0 <= s.congestion <= 1 for s in result.links.values()))
            self.assertTrue(all(s.flow == 0 for s in result.links.values() if s.closed))

    def test_actual_connected_road_receives_detour_traffic(self):
        identifier = 'kml_merged_e_8287_0_22'
        result = self.model.solve(8, {identifier})
        self.assertEqual(result.rerouted_demand, result.links[identifier].baseline)
        self.assertEqual(result.unmet_demand, 0)
        self.assertTrue(any(s.flow > s.baseline for s in result.links.values() if not s.closed))


if __name__ == '__main__':
    unittest.main()
