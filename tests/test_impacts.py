from dataclasses import replace
import unittest
from vredefort.data import Road, SpatialIndex, DATA
from vredefort.simulation_data import load_simulation_data
from vredefort.geometry import project
from vredefort.impacts import nearby_facilities, build_impact_report
from vredefort.traffic import TrafficDataset, TrafficModel
from test_traffic import model_fixture


class ImpactTests(unittest.TestCase):
    def test_used_routes_reconstruct_assigned_link_flow(self):
        model = model_fixture([('ab', 'a', 'b', 100), ('one', 'a', 'b', 120), ('two', 'a', 'b', 130)], [300, 10, 10])
        result = model.solve(0, {'ab'})
        self.assertAlmostEqual(sum(route.flow for route in result.routes), result.rerouted_demand)
        for identifier, state in result.links.items():
            assigned = sum(route.flow for route in result.routes if identifier in route.edge_ids)
            self.assertAlmostEqual(state.flow, (0 if state.closed else state.baseline) + assigned)

    def test_alternatives_are_ranked_connected_loopless_and_avoid_closures(self):
        model = model_fixture([('ab', 'a', 'b', 100), ('ac', 'a', 'c', 100), ('cb', 'c', 'b', 100),
                               ('ad', 'a', 'd', 110), ('db', 'd', 'b', 110), ('cd', 'c', 'd', 80)])
        result = model.solve(0, {'ab'})
        routes = model.diversion_paths('ab', result)
        self.assertEqual(len(routes), 3)
        self.assertEqual(len({route.edge_ids for route in routes}), 3)
        self.assertEqual([route.travel_time_s for route in routes], sorted(route.travel_time_s for route in routes))
        for route in routes:
            node, visited = route.source, {route.source}
            for identifier in route.edge_ids:
                self.assertFalse(result.links[identifier].closed)
                edge = model.edges[model.by_id[identifier]]
                self.assertIn(node, (edge['source'], edge['target']))
                node = edge['target'] if node == edge['source'] else edge['source']
                self.assertNotIn(node, visited)
                visited.add(node)
            self.assertEqual(node, route.target)
        another = model.solve(0, {'ab', 'ac'})
        self.assertTrue(all('ac' not in route.edge_ids for route in model.diversion_paths('ab', another)))

    def test_no_alternative_for_disconnected_loop_or_blocked_endpoint(self):
        model = model_fixture([('ab', 'a', 'b', 100), ('loop', 'b', 'b', 100)])
        self.assertEqual(model.diversion_paths('ab', model.solve(0, {'ab'})), ())
        self.assertEqual(model.diversion_paths('loop', model.solve(0, {'loop'})), ())
        self.assertEqual(model.diversion_paths('ab', model.solve(0, blocked_nodes={'a'})), ())

    def test_facilities_buffer_is_geometric_not_an_outage_claim(self):
        a, b = project(77.6, 12.9), project(77.61, 12.9)
        road = Road('road', {}, ((a, b),), (a[0], a[1], b[0], b[1]))
        view = {'roads': [road], 'index': SpatialIndex([road.bounds])}
        def point(lat, name):
            return {'Name': name, 'coordinate': (77.605, lat), 'point': project(77.605, lat)}
        facilities = {'hospitals': [point(12.901, 'Near'), point(12.91, 'Far')], 'fire': []}
        report = nearby_facilities(view, facilities, frozenset({'road'}), frozenset())
        self.assertEqual(len(report), 1)
        self.assertEqual(report[0].name, 'Near')
        self.assertTrue(report[0].near_closed)
        self.assertAlmostEqual(report[0].distance_m, 111.2, delta=1)
        self.assertEqual(report[0].road_ids, ('road',))
        self.assertEqual(nearby_facilities(view, facilities, frozenset(), frozenset()), ())


class ActualImpactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.model = load_simulation_data()

    def test_actual_report_includes_every_changed_road_and_feasible_preview(self):
        identifier = 'kml_merged_e_8287_0_22'
        result = self.model.solve(8, {identifier})
        report = build_impact_report(self.model, result, self.data, {identifier})
        self.assertEqual(report.closed_roads, {identifier})
        self.assertEqual(report.loaded_roads, {key for key, state in result.links.items() if state.flow > state.baseline})
        self.assertTrue(report.diversions)
        self.assertFalse(report.unavailable)
        for option in report.diversions:
            self.assertNotIn(identifier, option.route.edge_ids)
            self.assertTrue(all(not result.links[key].closed for key in option.route.edge_ids))
        for facility in report.facilities:
            self.assertLessEqual(facility.distance_m, 250)
            self.assertTrue(set(facility.road_ids) <= report.affected_roads)
        no_closure = self.model.solve(8)
        empty = build_impact_report(self.model, no_closure, self.data, set())
        self.assertFalse(empty.affected_roads or empty.facilities or empty.diversions)
