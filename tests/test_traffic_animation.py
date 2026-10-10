import math
import unittest
from dataclasses import replace
from unittest.mock import patch
from citycollapse.traffic_animation import (FlowPath, clip_segment, visible_paths,
                                            point_at, trail_segments, path_slice, FlowLayer)


class RecordingCanvas:
    def __init__(self):
        self.items = {}

    def create_line(self, *points, **style):
        identifier = len(self.items)
        self.items[identifier] = {'coords': points, **style}
        return identifier

    def itemconfigure(self, identifier, **style):
        self.items[identifier].update(style)

    def coords(self, identifier, *points):
        self.items[identifier]['coords'] = points


class TrafficAnimationTests(unittest.TestCase):
    def setUp(self):
        # An L-shaped road: highlights must turn the corner, not cut across it.
        self.path = FlowPath('road', ((0., 0.), (20., 0.), (20., 20.)),
                             (0., 20., 40.), 10., .5)

    def test_fractional_motion_is_continuous_and_follows_curve(self):
        self.assertEqual(point_at(self.path, 20.5), (20., .5))
        self.assertEqual(path_slice(self.path, 18., 22.), (18., 0., 20., 0., 20., 2.))
        a = trail_segments(self.path, 2.05)[0]
        b = trail_segments(self.path, 2.06)[0]
        self.assertAlmostEqual(a[-1], .5)
        self.assertAlmostEqual(b[-1] - a[-1], .1)

    def test_wrapping_tail_has_no_line_across_disconnected_endpoints(self):
        parts = trail_segments(self.path, .1)
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0][-2:], (20., 20.))
        self.assertEqual(parts[1][:2], (0., 0.))
        self.assertTrue(all(math.isfinite(value) for part in parts for value in part))
        self.assertEqual(parts, trail_segments(self.path, 4.1))

    def test_clipping_splits_reentry_without_bridging_offscreen_gap(self):
        bounds = (0., 0., 10., 10.)
        self.assertEqual(clip_segment((-20, 5), (20, 5), bounds), ((0., 5.), (10., 5.)))
        self.assertIsNone(clip_segment((-20, -5), (20, -5), bounds))
        pieces = visible_paths(((5, 5), (15, 5), (15, 8), (5, 8)), bounds)
        self.assertEqual(pieces, [((5., 5.), (10., 5.)), ((10., 8.), (5., 8.))])

    def test_speed_update_preserves_positions_and_blocking_hides_motion(self):
        canvas, camera = RecordingCanvas(), object()
        layer = FlowLayer(canvas)
        layer.install(camera, [self.path], elapsed=12.3)
        layer.draw(camera, 12.3)
        before = {key: value['coords'] for key, value in canvas.items.items() if value['state'] == 'normal'}
        layer.install(camera, [replace(self.path, speed=30)], elapsed=12.3)
        layer.draw(camera, 12.3)
        after = {key: value['coords'] for key, value in canvas.items.items() if value['state'] == 'normal'}
        self.assertEqual(before.keys(), after.keys())
        for key in before:
            for a, b in zip(before[key], after[key]):
                self.assertAlmostEqual(a, b)
        layer.draw(camera, 12.4)
        self.assertTrue(any(canvas.items[key]['coords'] != points for key, points in after.items()))
        layer.set_blocked({'road'})
        layer.draw(camera, 12.4)
        self.assertTrue(all(value['state'] == 'hidden' for value in canvas.items.values()))

    def test_paused_frames_skip_tk_updates_and_resume_after_hiding(self):
        canvas, camera = RecordingCanvas(), object()
        layer = FlowLayer(canvas)
        layer.install(camera, [self.path])
        layer.draw(camera, 5)
        with patch.object(canvas, 'coords', wraps=canvas.coords) as coords:
            for _ in range(60):
                layer.draw(camera, 5)
            coords.assert_not_called()
            layer.hide()
            layer.draw(camera, 5)
            self.assertTrue(coords.called)
            self.assertTrue(any(value['state'] == 'normal' for value in canvas.items.values()))
            coords.reset_mock()
            layer.draw(camera, 5.033)
            self.assertTrue(coords.called)


if __name__ == '__main__':
    unittest.main()
