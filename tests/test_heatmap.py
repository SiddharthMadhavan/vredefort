from dataclasses import replace
from types import SimpleNamespace
import unittest

from citycollapse.map_renderer import Camera
from citycollapse.traffic import LinkState
from citycollapse.traffic_rendering import paint_heatmap, paint_traffic, congestion_hotspots


class HeatmapTests(unittest.TestCase):
    def setUp(self):
        self.camera = Camera(.5, .5, 11, 192, 128)
        self.geometry = [('road', ((24, 64), (168, 64)))]
        self.state = LinkState(100, 100, 200, 30, .2, 1)
        self.view = {'nodes': []}

    def result(self, state=None):
        return SimpleNamespace(links={'road': state or self.state}, blocked_nodes=frozenset())

    def test_heatmap_is_optional_and_extends_beyond_the_road_glow(self):
        normal = paint_traffic(self.camera, self.view, self.result(), geometry=self.geometry)
        off = paint_traffic(self.camera, self.view, self.result(), geometry=self.geometry, heatmap=False)
        on = paint_traffic(self.camera, self.view, self.result(), geometry=self.geometry, heatmap=True)
        self.assertEqual(normal.tobytes(), off.tobytes())
        self.assertGreater(on.getpixel((96, 42))[3], off.getpixel((96, 42))[3])
        self.assertGreater(on.getpixel((96, 64))[3], on.getpixel((96, 8))[3])

    def test_high_congestion_is_redder_and_stronger_than_low_congestion(self):
        low = paint_heatmap(self.camera, self.geometry, self.result(replace(self.state, congestion=0)))
        high = paint_heatmap(self.camera, self.geometry, self.result(replace(self.state, congestion=1)))
        r, g, _, alpha_low = low.getpixel((96, 64))
        self.assertGreater(g, r)
        r, g, _, alpha_high = high.getpixel((96, 64))
        self.assertGreater(r, g)
        self.assertGreater(alpha_high, alpha_low)

    def test_closed_or_zero_flow_roads_do_not_generate_heat(self):
        for state in (replace(self.state, closed=True, flow=0), replace(self.state, flow=0)):
            heat = paint_heatmap(self.camera, self.geometry, self.result(state))
            self.assertIsNone(heat.getbbox())
        result = self.result(replace(self.state, closed=True, flow=0))
        normal = paint_traffic(self.camera, self.view, result, geometry=self.geometry)
        heated = paint_traffic(self.camera, self.view, result, geometry=self.geometry, heatmap=True)
        self.assertEqual(normal.tobytes(), heated.tobytes(), 'Closure markers must remain visible')

    def test_vertex_density_does_not_change_heat_and_input_state_is_unchanged(self):
        result = self.result()
        dense = [('road', tuple((x, 64) for x in range(24, 169, 4)))]
        coarse = paint_heatmap(self.camera, self.geometry, result)
        detailed = paint_heatmap(self.camera, dense, result)
        self.assertEqual(coarse.tobytes(), detailed.tobytes())
        self.assertEqual(result.links['road'], self.state)

    def test_nearby_heavy_roads_group_and_distant_roads_remain_separate(self):
        camera = replace(self.camera, width=600, height=300)
        geometry = [('a', ((80, 90), (120, 90))), ('b', ((85, 110), (125, 110))),
                    ('c', ((460, 100), (500, 100)))]
        result = SimpleNamespace(links={key: replace(self.state, congestion=.85) for key in ('a', 'b', 'c')})
        circles = congestion_hotspots(camera, geometry, result)
        self.assertEqual(len(circles), 2)
        self.assertAlmostEqual(circles[0][0], 102.5)
        self.assertAlmostEqual(circles[0][1], 100)
        for x, y, radius, _ in circles:
            self.assertGreaterEqual(radius, 38)
            self.assertTrue(0 <= x <= camera.width and 0 <= y <= camera.height)
        result.links['a'] = replace(result.links['a'], closed=True, flow=0)
        result.links['b'] = replace(result.links['b'], congestion=.69)
        self.assertEqual(len(congestion_hotspots(camera, geometry, result)), 1)

    def test_hotspot_circle_has_a_visible_border_glow_and_keeps_density_independence(self):
        result = self.result(replace(self.state, congestion=.9))
        circles = congestion_hotspots(self.camera, self.geometry, result)
        x, y, radius, _ = circles[0]
        heat = paint_heatmap(self.camera, self.geometry, result)
        border = heat.getpixel((round(x), round(y - radius)))
        halo = heat.getpixel((round(x), max(0, round(y - radius - 5))))
        self.assertGreater(border[3], halo[3])
        self.assertGreater(halo[3], 0, 'Circle border needs a soft halo')
        dense = [('road', tuple((px, 64) for px in range(24, 169, 4)))]
        self.assertEqual(circles, congestion_hotspots(self.camera, dense, result))


if __name__ == '__main__':
    unittest.main()
