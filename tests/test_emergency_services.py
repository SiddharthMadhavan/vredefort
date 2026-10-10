from concurrent.futures import CancelledError
from dataclasses import replace
import math
from threading import Event
from types import SimpleNamespace
import unittest
from PIL import Image

from citycollapse.data import Road, SpatialIndex
from citycollapse.geometry import project
from citycollapse.emergency_services import EmergencyAccessModel
from citycollapse.emergency_rendering import paint_emergency, visible_risks, route_paths, trim_paths, paint_emergency_route
from citycollapse.map_renderer import Camera
from citycollapse.simulation_data import load_simulation_data
from test_traffic import model_fixture


def fixture(edges, coordinates, facilities):
    model = model_fixture(edges)
    nodes = [{'id': key, 'number': index + 1, 'coordinate': value, 'point': project(*value)}
             for index, (key, value) in enumerate(coordinates.items())]
    roads = []
    for edge in model.edges:
        a, b = project(*coordinates[edge['source']]), project(*coordinates[edge['target']])
        bounds = min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])
        roads.append(Road(edge['id'], edge, ((a, b),), bounds))
    data = {'graph': {'nodes': nodes}, 'views': {'KML road graph': {
        'roads': roads, 'index': SpatialIndex([r.bounds for r in roads])}}, 'fire': [], 'hospitals': []}
    for kind, name, lon_lat in facilities:
        data[kind].append({'Name': name, 'coordinate': lon_lat, 'point': project(*lon_lat),
                           'match_status': 'provided_coordinates'})
    return model, data


class EmergencyTests(unittest.TestCase):
    def test_facility_mid_edge_seeds_fractional_cost_both_directions(self):
        model, data = fixture([('ab', 'a', 'b', 1000)], {'a': (77.6, 13), 'b': (77.61, 13)},
                              [('fire', 'Station', (77.605, 13))])
        analyzer = EmergencyAccessModel(model, data)
        baseline = model.solve(0)
        r = analyzer.analyze(baseline, baseline)
        self.assertEqual(len(r.anchors), 1)
        for point in r.points:
            if point.kind == 'fire':
                self.assertAlmostEqual(point.seconds, 50, places=5)
                self.assertEqual(point.facility.name, 'Station')
                self.assertEqual(point.status, 'normal')
                self.assertEqual(point.added_seconds, 0)
                route = r.route(point)
                self.assertEqual(route.edge_ids, ('ab',))
                self.assertAlmostEqual(abs(route.legs[0].end_fraction - route.legs[0].start_fraction), .5)
            else:
                self.assertEqual(point.status, 'gap')
                self.assertIsNone(r.route(point))

    def test_reversed_geometry_keeps_source_target_costs_correct(self):
        model, data = fixture([('ab', 'a', 'b', 1000)], {'a': (77.6, 13), 'b': (77.61, 13)},
                              [('fire', 'Station', (77.602, 13))])
        road = data['views']['KML road graph']['roads'][0]
        data['views']['KML road graph']['roads'][0] = replace(road, paths=(tuple(reversed(road.paths[0])),))
        baseline = model.solve(0)
        result = EmergencyAccessModel(model, data).analyze(baseline, baseline)
        by_id = {p.node_id: p for p in result.points if p.kind == 'fire'}
        self.assertAlmostEqual(by_id['a'].seconds, 20, places=5)
        self.assertAlmostEqual(by_id['b'].seconds, 80, places=5)

    def test_closure_reroutes_and_uses_updated_speeds(self):
        model, data = fixture([('sa', 's', 'a', 100), ('ab', 'a', 'b', 100),
                               ('ac', 'a', 'c', 100), ('cb', 'c', 'b', 100)],
            {'s': (77.59, 13), 'a': (77.60, 13), 'b': (77.61, 13), 'c': (77.605, 13.01)},
            [('fire', 'Station', (77.59, 13)), ('hospitals', 'Hospital', (77.61, 13))])
        analyzer, baseline = EmergencyAccessModel(model, data), model.solve(0)
        scenario = model.solve(0, {'ab'})
        r = analyzer.analyze(baseline, scenario, threshold_s=1000, added_threshold_s=1)
        point = next(p for p in r.points if p.node_id == 'b' and p.kind == 'fire')
        expected = sum(model.edges[model.by_id[key]]['length_m'] / (scenario.links[key].speed / 3.6)
                       for key in ('sa', 'ac', 'cb'))
        self.assertAlmostEqual(point.seconds, expected)
        self.assertAlmostEqual(point.baseline_seconds, 20)
        self.assertEqual(point.status, 'degraded')
        route = r.route(point)
        self.assertEqual(route.edge_ids, ('sa', 'ac', 'cb'))
        self.assertEqual(route.node_id, 'b')
        self.assertEqual(route.facility, point.facility)
        self.assertAlmostEqual(sum(model.edges[model.by_id[leg.edge_id]]['length_m'] *
            abs(leg.end_fraction - leg.start_fraction) / (scenario.links[leg.edge_id].speed / 3.6)
            for leg in route.legs), point.seconds)
        slower = replace(scenario, links={key: replace(link, speed=link.speed / 2) for key, link in scenario.links.items()})
        slow = analyzer.analyze(baseline, slower)
        self.assertAlmostEqual(next(p.seconds for p in slow.points if p.node_id == 'b' and p.kind == 'fire'), expected * 2)

    def test_lost_access_is_separate_from_existing_disconnected_gap(self):
        model, data = fixture([('sa', 's', 'a', 100), ('ab', 'a', 'b', 100), ('xy', 'x', 'y', 100)],
            {'s': (77.59, 13), 'a': (77.60, 13), 'b': (77.61, 13), 'x': (77.7, 13), 'y': (77.71, 13)},
            [('fire', 'Station', (77.59, 13))])
        baseline = model.solve(0)
        analyzer = EmergencyAccessModel(model, data)
        r = analyzer.analyze(baseline, model.solve(0, {'ab'}))
        points = {p.node_id: p for p in r.points if p.kind == 'fire'}
        self.assertEqual(points['b'].status, 'lost')
        self.assertIsNone(r.route(points['b']))
        self.assertEqual(points['x'].status, 'gap')
        self.assertEqual(points['s'].status, 'normal')
        blocked = analyzer.analyze(baseline, model.solve(0, blocked_nodes={'a'}))
        self.assertEqual(next(p.status for p in blocked.points if p.node_id == 'a' and p.kind == 'fire'), 'lost')

    def test_fastest_facility_can_change_and_far_facilities_are_excluded(self):
        model, data = fixture([('ab', 'a', 'b', 1000), ('bc', 'b', 'c', 100)],
            {'a': (77.59, 13), 'b': (77.60, 13), 'c': (77.61, 13)},
            [('fire', 'West', (77.59, 13)), ('fire', 'East', (77.61, 13)), ('fire', 'Far', (78, 14))])
        analyzer, baseline = EmergencyAccessModel(model, data), model.solve(0)
        r = analyzer.analyze(baseline, baseline)
        self.assertEqual(len(r.skipped), 1)
        self.assertEqual(next(p.facility.name for p in r.points if p.node_id == 'b' and p.kind == 'fire'), 'East')
        r = analyzer.analyze(baseline, model.solve(0, {'bc'}))
        self.assertEqual(next(p.facility.name for p in r.points if p.node_id == 'b' and p.kind == 'fire'), 'West')

    def test_partial_geometry_preserves_bends_direction_and_reversed_road(self):
        curve = (((0., 0.), (1., 0.), (1., 1.)),)
        expected = (((.5, 0.), (1., 0.), (1., .5)),)
        self.assertEqual(trim_paths(curve, .25, .75), expected)
        self.assertEqual(trim_paths(curve, .75, .25), (tuple(reversed(expected[0])),))
        model, data = fixture([('ab', 'a', 'b', 1000)], {'a': (77.6, 13), 'b': (77.61, 13)},
                              [('hospitals', 'Hospital', (77.602, 13))])
        road = data['views']['KML road graph']['roads'][0]
        road = replace(road, paths=(tuple(reversed(road.paths[0])),))
        data['views']['KML road graph']['roads'][0] = road
        analyzer, baseline = EmergencyAccessModel(model, data), model.solve(0)
        r = analyzer.analyze(baseline, baseline)
        point = next(p for p in r.points if p.kind == 'hospitals' and p.node_id == 'b')
        network = SimpleNamespace(roads_by_id={'ab': road}, nodes_by_id={n['id']: n for n in data['graph']['nodes']})
        route = r.route(point)
        geometry = route_paths(network, route)
        self.assertAlmostEqual(math.dist(geometry[0][0], route.facility.point), 0, places=12)
        self.assertEqual(geometry[-1][-1], point.point)
        self.assertNotEqual(geometry[0][0], road.paths[0][-1])

    def test_cancel_and_baseline_validation(self):
        model, data = fixture([('ab', 'a', 'b', 1000)], {'a': (77.6, 13), 'b': (77.61, 13)}, [])
        cancel = Event()
        cancel.set()
        analyzer = EmergencyAccessModel(model, data)
        baseline = model.solve(0)
        with self.assertRaises(CancelledError):
            analyzer.analyze(baseline, baseline, cancel=cancel)
        with self.assertRaises(ValueError):
            analyzer.analyze(replace(baseline, hour=1), baseline)
        with self.assertRaises(ValueError):
            analyzer.analyze(baseline, baseline, threshold_s=0)


class ActualEmergencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.model = load_simulation_data()
        cls.analyzer = EmergencyAccessModel(cls.model, cls.data)

    def test_all_junctions_real_facility_sources_and_monotone_closure_costs(self):
        baseline = self.model.solve(8)
        result = self.analyzer.analyze(baseline, self.model.solve(8, {'kml_merged_e_8287_0_22'}))
        self.assertEqual(len(result.points), len(self.data['graph']['nodes']) * 2)
        self.assertEqual(len(result.anchors) + len(result.skipped), 46)
        for anchor in result.anchors:
            self.assertIn(anchor.edge_id, baseline.links)
            self.assertLessEqual(anchor.distance_m, 250)
        for point in result.points:
            self.assertGreaterEqual(point.seconds + 1e-8, point.baseline_seconds)

    def test_actual_routes_reproduce_every_travel_time_and_avoid_closures(self):
        baseline = self.model.solve(8)
        scenario = self.model.solve(8, {'kml_merged_e_8287_0_22'})
        report = self.analyzer.analyze(baseline, scenario)
        for point in report.points:
            route = report.route(point)
            if route is None:
                self.assertFalse(math.isfinite(point.seconds))
                continue
            travel = 0.
            for leg in route.legs:
                edge = self.model.edges[self.model.by_id[leg.edge_id]]
                state = scenario.links[leg.edge_id]
                self.assertFalse(state.closed)
                travel += edge['length_m'] * abs(leg.end_fraction - leg.start_fraction) / (state.speed / 3.6)
            self.assertAlmostEqual(travel, point.seconds, places=7)
            self.assertEqual(route.facility, point.facility)

    def test_overlay_uses_actual_junctions_and_kind_filter(self):
        baseline = self.model.solve(8)
        result = self.analyzer.analyze(baseline, baseline)
        camera = Camera(*project(77.5946, 12.9716), 11, 1000, 700)
        markers = visible_risks(camera, result, 'fire')
        self.assertTrue(markers)
        self.assertTrue(all(p.kind == 'fire' for x, y, p in markers))
        self.assertEqual(len(markers), len({(int(x // 24), int(y // 24)) for x, y, p in markers}))
        image = Image.new('RGBA', (1000, 700))
        paint_emergency(image, camera, result, 'fire')
        self.assertIsNotNone(image.getbbox())
