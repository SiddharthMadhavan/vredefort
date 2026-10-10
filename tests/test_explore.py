"""Checks for the road explorer's geometry, selection and dataset integrity."""
import unittest
from unittest.mock import patch
from PIL import Image

from vredefort.data import Road, SpatialIndex
from vredefort.explore_map import (
    RoadNetwork, load_network, nearest_node, nearest_road, paint_explore, ExplorePainter,
)
from vredefort.geometry import project, unproject
from vredefort.map_renderer import Camera


class ExplorerTests(unittest.TestCase):
    def setUp(self):
        self.camera = Camera(.5, .5, 16, 256, 256)
        self.a = self.make_road('a', [(40, 100), (120, 100), (120, 180)])
        self.b = self.make_road('b', [(200, 60), (200, 200)])
        roads = [self.a, self.b]
        nodes = [
            {'id': 'n1', 'point': self.a.paths[0][0]},
            {'id': 'n2', 'point': self.a.paths[0][-1]},
            {'id': 'n3', 'point': self.b.paths[0][0]},
            {'id': 'n4', 'point': self.b.paths[0][-1]},
        ]
        self.network = RoadNetwork(
            roads, SpatialIndex(road.bounds for road in roads), nodes,
            SpatialIndex((*node['point'], *node['point']) for node in nodes),
            {road.id: road for road in roads}, {node['id']: node for node in nodes},
            {'n1': ['a'], 'n2': ['a'], 'n3': ['b'], 'n4': ['b']})

    def make_road(self, identifier, points):
        path = tuple(self.camera.world(*point) for point in points)
        xs, ys = zip(*path)
        source, target = ('n1', 'n2') if identifier == 'a' else ('n3', 'n4')
        return Road(identifier, {'source': source, 'target': target}, (path,),
                    (min(xs), min(ys), max(xs), max(ys)))

    def test_coordinate_round_trip(self):
        coordinate = 77.5946, 12.9716
        for expected, actual in zip(coordinate, unproject(*project(*coordinate))):
            self.assertAlmostEqual(expected, actual, places=10)
        for point in [(0, 0), (120, 180), (256, 256)]:
            for expected, actual in zip(point, self.camera.screen(self.camera.world(*point))):
                self.assertAlmostEqual(expected, actual)

    def test_road_selection_follows_curved_geometry(self):
        self.assertEqual(nearest_road(self.network, self.camera, 80, 104).id, 'a')
        self.assertEqual(nearest_road(self.network, self.camera, 124, 150).id, 'a')
        self.assertIsNone(nearest_road(self.network, self.camera, 80, 120))

    def test_node_selection_has_a_small_target(self):
        self.assertEqual(nearest_node(self.network, self.camera, 40, 100)['id'], 'n1')
        self.assertIsNone(nearest_node(self.network, self.camera, 80, 100))
        self.assertIsNone(nearest_node(self.network, self.camera, 40, 112))

    def test_selection_keeps_other_roads_visible(self):
        normal = paint_explore(self.camera, {}, self.network, None)
        selected = paint_explore(self.camera, {}, self.network, ('road', 'a'))
        self.assertNotEqual(normal.getpixel((80, 100)), selected.getpixel((80, 100)))
        self.assertEqual(normal.getpixel((200, 150)), selected.getpixel((200, 150)))

    def test_node_selection_highlights_its_connected_edges(self):
        normal = paint_explore(self.camera, {}, self.network, None)
        selected = paint_explore(self.camera, {}, self.network, ('node', 'n1'))
        self.assertNotEqual(normal.getpixel((80, 100)), selected.getpixel((80, 100)))
        self.assertEqual(normal.getpixel((200, 150)), selected.getpixel((200, 150)))

    def test_selection_reuses_base_and_tile_replacement_invalidates_it(self):
        from vredefort import explore_map
        painter = ExplorePainter()
        with patch.object(explore_map, '_paint_base', wraps=explore_map._paint_base) as render:
            normal = painter.paint(self.camera, {}, self.network, None)
            selected = painter.paint(self.camera, {}, self.network, ('road', 'a'))
            cleared = painter.paint(self.camera, {}, self.network, None)
            self.assertEqual(render.call_count, 1)
            self.assertEqual(normal.tobytes(), cleared.tobytes())
            self.assertNotEqual(normal.tobytes(), selected.tobytes())
            # Callers may modify returned images without corrupting the cache.
            cleared.paste((255, 0, 0), (0, 0, 256, 256))
            self.assertEqual(normal.tobytes(), painter.paint(self.camera, {}, self.network, None).tobytes())
            key = self.camera.tile_keys()[0]
            painter.paint(self.camera, {key: Image.new('RGB', (256, 256), 'green')}, self.network, None)
            painter.paint(self.camera, {key: Image.new('RGB', (256, 256), 'blue')}, self.network, None)
            self.assertEqual(render.call_count, 3)

    def test_real_graph_connections_reference_existing_edges_and_nodes(self):
        network = load_network()
        self.assertTrue(network.roads and network.nodes)
        self.assertEqual(len(network.roads), len(network.roads_by_id))
        self.assertEqual(len(network.nodes), len(network.nodes_by_id))
        for road in network.roads:
            self.assertGreater(road.properties['length_m'], 0)
            for node_id in (road.properties['source'], road.properties['target']):
                self.assertIn(node_id, network.nodes_by_id)
                self.assertIn(road.id, network.edge_ids[node_id])
        for node_id, edges in network.edge_ids.items():
            for edge_id in edges:
                road = network.roads_by_id[edge_id]
                self.assertIn(node_id, (road.properties['source'], road.properties['target']))


if __name__ == '__main__':
    unittest.main()
