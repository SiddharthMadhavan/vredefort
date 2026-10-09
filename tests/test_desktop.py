import math
import unittest
from citycollapse.data import load_datasets, SpatialIndex
from citycollapse.geometry import project, unproject, cumulative_lengths, position_along
from citycollapse.map_renderer import Camera, width_style
from citycollapse.simulation import Simulation

class GeometryTests(unittest.TestCase):
    def test_mercator_and_camera_round_trip(self):
        point = (77.5946, 12.9716)
        actual = unproject(*project(*point))
        for expected, value in zip(point, actual):
            self.assertAlmostEqual(expected, value, places=10)
        camera = Camera(*project(*point), 11, 1400, 900)
        self.assertEqual(camera.screen(project(*point)), (700, 450))
        for expected, value in zip(project(77.6, 12.98), camera.world(*camera.screen(project(77.6, 12.98)))):
            self.assertAlmostEqual(expected, value, places=12)

    def test_position_follows_curve(self):
        coordinates = [(77.5, 12.9), (77.51, 12.9), (77.51, 12.91)]
        lengths = cumulative_lengths(coordinates)
        self.assertEqual(position_along(coordinates, lengths, 0, 100)[0], coordinates[0])
        self.assertEqual(position_along(coordinates, lengths, 100, 100)[0], coordinates[-1])
        point, _ = position_along(coordinates, lengths, 75, 100)
        self.assertEqual(point[0], 77.51)
        self.assertGreater(point[1], 12.9)
        with self.assertRaises(ValueError):
            position_along(coordinates, lengths, 101, 100)

    def test_spatial_index_long_roads_and_points(self):
        index = SpatialIndex([(0, 0, .9, .9), (.5, .5, .5, .5), (.6, .6, .6, .6)])
        self.assertEqual(index.query((.49999, .49999, .50001, .50001)), {0, 1})

class DatasetSimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_datasets()

    def test_data_preserved(self):
        self.assertEqual(len(self.data['views']['KML width shading']['roads']), 23238)
        self.assertEqual(len(self.data['graph']['nodes']), 3309)
        self.assertEqual(len(self.data['graph']['edges']), 4448)
        self.assertEqual(len(self.data['hospitals']), 25)
        self.assertEqual(len(self.data['fire']), 21)
        self.assertNotIn('continuation', {node['kind'] for node in self.data['graph']['nodes']})

    def test_width_palette_and_subtle_thickness(self):
        statistics = self.data['width_metadata']['widthFields']
        for field in ('RR_WIDTH_P', 'RR_width_B'):
            narrow, thickness = width_style({field: statistics[field]['min']}, field, statistics)
            wide, wide_thickness = width_style({field: statistics[field]['max']}, field, statistics)
            self.assertEqual(narrow, (138, 146, 144))
            self.assertTrue(all(a > b for a, b in zip(narrow, wide)))
            self.assertAlmostEqual(wide_thickness / thickness, 1.35)

    def test_reinitialization_seed_and_many_cars(self):
        sim = Simulation(self.data['graph'])
        first = [car.distance_m for car in sim.initialize_cars(5, seed=42)]
        self.assertEqual(first, [car.distance_m for car in sim.initialize_cars(5, seed=42)])
        self.assertEqual([car.edge['id'] for car in sim.vehicles], [edge['id'] for edge in self.data['graph']['edges'][:5]])
        sim.initialize_cars(10000, seed=7)
        self.assertEqual(len({car.id for car in sim.vehicles}), 10000)
        sim.get_next_state(.1, 100)
        self.assertTrue(all(0 <= car.distance_m <= car.edge['length_m'] for car in sim.vehicles))
        self.assertAlmostEqual(sim.elapsed_s, .1)

    def test_movement_and_end_of_edge(self):
        sim = Simulation(self.data['graph'])
        car = sim.initialize_cars(1, seed=1)[0]
        before = car.distance_m
        sim.get_next_state(.01, 100)
        self.assertAlmostEqual(car.distance_m, before + 1)
        sim.get_next_state(100000, 100)
        self.assertTrue(car.stopped)
        self.assertEqual(car.distance_m, car.edge['length_m'])
        self.assertEqual(car.position()[0], tuple(car.edge['coordinates'][-1]))
        for dt, speed in [(-1, 100), (1, -1), (math.nan, 100), (1, math.inf)]:
            with self.assertRaises(ValueError):
                sim.get_next_state(dt, speed)

if __name__ == '__main__':
    unittest.main()
