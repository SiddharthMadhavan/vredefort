"""Lightweight, elapsed-time road trails drawn by the existing Tk event loop.

These are visual flow cues, not vehicles or inferred one-way directions.
The static glow is painted once; motion never redraws a full map bitmap.
"""
from bisect import bisect_right
from dataclasses import dataclass
import math
import zlib


def clip_segment(a, b, bounds):
    """Liang-Barsky clipping keeps offscreen road length out of the animation."""
    left, top, right, bottom = bounds
    dx, dy = b[0] - a[0], b[1] - a[1]
    low, high = 0.0, 1.0
    for p, q in ((-dx, a[0] - left), (dx, right - a[0]),
                 (-dy, a[1] - top), (dy, bottom - a[1])):
        if p == 0:
            if q < 0:
                return None
        else:
            ratio = q / p
            if p < 0:
                low = max(low, ratio)
            else:
                high = min(high, ratio)
            if low > high:
                return None
    return ((a[0] + low * dx, a[1] + low * dy),
            (a[0] + high * dx, a[1] + high * dy))


def visible_paths(points, bounds):
    paths, current = [], []
    for a, b in zip(points, points[1:]):
        segment = clip_segment(a, b, bounds)
        if segment is None:
            if len(current) > 1:
                paths.append(tuple(current))
            current = []
            continue
        start, end = segment
        if current and math.dist(current[-1], start) > 1e-6:
            if len(current) > 1:
                paths.append(tuple(current))
            current = []
        if not current:
            current.append(start)
        if math.dist(current[-1], end) > 1e-6:
            current.append(end)
    if len(current) > 1:
        paths.append(tuple(current))
    return paths


@dataclass(frozen=True, slots=True)
class FlowPath:
    identifier: str
    points: tuple
    distances: tuple
    speed: float
    congestion: float

    @property
    def length(self):
        return self.distances[-1]


def prepare_flow_paths(camera, geometry, result):
    paths = []
    bounds = (-16, -16, camera.width + 16, camera.height + 16)
    for identifier, points in geometry:
        state = result.links[identifier]
        if state.closed or state.flow <= 0:
            continue
        for visible in visible_paths(points, bounds):
            distances = [0.0]
            for a, b in zip(visible, visible[1:]):
                distances.append(distances[-1] + math.dist(a, b))
            if distances[-1] >= 24:
                paths.append(FlowPath(identifier, visible, tuple(distances),
                                      max(12.0, min(48.0, state.speed * .7)), state.congestion))
    # Motion has a viewport budget; all roads retain their actual static color.
    return tuple(sorted(paths, key=lambda path: (-path.length, path.identifier)))


def point_at(path, distance):
    distance = max(0.0, min(path.length, distance))
    index = min(len(path.points) - 2, max(0, bisect_right(path.distances, distance) - 1))
    a, b = path.points[index:index + 2]
    segment_length = path.distances[index + 1] - path.distances[index]
    ratio = (distance - path.distances[index]) / segment_length if segment_length else 0.0
    return a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio


def path_slice(path, start, end):
    """Include intervening vertices so highlights bend with the road."""
    points = [point_at(path, start)]
    first, last = bisect_right(path.distances, start), bisect_right(path.distances, end)
    points.extend(path.points[first:last])
    points.append(point_at(path, end))
    return tuple(value for point in points for value in point)


def trail_segments(path, elapsed, offset=0.0, direction=1):
    """At most two continuous pieces, including a tail crossing the path seam."""
    head = (elapsed * path.speed * direction + offset * path.length) % path.length
    length = min(path.length * .35, 10 + 9 * path.congestion)
    start = (head - length if direction > 0 else head) % path.length
    end = start + length
    if end <= path.length:
        return (path_slice(path, start, end),)
    return (path_slice(path, start, path.length), path_slice(path, 0, end - path.length))


class FlowLayer:
    MAX_TRAILS = 420

    def __init__(self, canvas):
        self.canvas = canvas
        self.camera, self.trails = None, []
        self.items, self.visibility = [], {}
        self.origins = {}
        self.blocked = frozenset()
        self.enabled, self.dirty = False, True

    def _show(self, item, visible):
        if self.visibility.get(item) != visible:
            self.canvas.itemconfigure(item, state='normal' if visible else 'hidden')
            self.visibility[item] = visible

    def hide(self):
        for item in self.items:
            self._show(item, False)
        self.enabled = False

    def set_blocked(self, identifiers):
        self.blocked = frozenset(identifiers)
        self.dirty = True

    def install(self, camera, paths, elapsed=0.0):
        from .map_renderer import traffic_color
        previous = self.origins if camera == self.camera else {}
        origins = {}
        self.camera, self.trails = camera, []
        for path in paths:
            key = (path.identifier, path.points[0], path.points[-1], path.length)
            if key in previous:
                distance, started, speed = previous[key]
                distance += (elapsed - started) * speed
            else:
                distance = elapsed * path.speed
            origins[key] = (distance, elapsed, path.speed)
            count = (2 if path.length >= 80 else 1) + (1 if path.congestion >= .65 else 0)
            seed = zlib.crc32(path.identifier.encode()) / 2 ** 32
            for i in range(count):
                if len(self.trails) >= self.MAX_TRAILS:
                    break
                # Adding denser trails does not reposition the existing ones.
                self.trails.append((path, (seed + i * .38196601125) % 1, 1 if i % 2 == 0 else -1))
            if len(self.trails) >= self.MAX_TRAILS:
                break
        self.origins = origins
        needed = len(self.trails) * 4  # Two pieces, each with a soft rim and core.
        while len(self.items) < needed:
            item = self.canvas.create_line(0, 0, 0, 0, state='hidden',
                                           capstyle='round', joinstyle='round', tags='traffic-flow')
            self.items.append(item)
            self.visibility[item] = False
        for i, (path, _, _) in enumerate(self.trails):
            color = traffic_color(path.congestion)
            rim = '#%02x%02x%02x' % tuple(round(c * .7) for c in color)
            core = '#%02x%02x%02x' % tuple(round(c + (255 - c) * .55) for c in color)
            for piece in range(2):
                self.canvas.itemconfigure(self.items[i * 4 + piece * 2], fill=rim, width=5 + path.congestion)
                self.canvas.itemconfigure(self.items[i * 4 + piece * 2 + 1], fill=core, width=1.5 + path.congestion)
        for item in self.items[needed:]:
            self._show(item, False)
        self.dirty = True

    def draw(self, camera, elapsed, enabled=True):
        if not enabled or camera != self.camera:
            self.hide()
            return
        self.enabled = True
        for i, (path, offset, direction) in enumerate(self.trails):
            key = (path.identifier, path.points[0], path.points[-1], path.length)
            distance, started, _ = self.origins[key]
            segments = () if path.identifier in self.blocked else trail_segments(
                path, elapsed - started, offset + direction * distance / path.length, direction)
            for piece in range(2):
                visible = piece < len(segments)
                for item in self.items[i * 4 + piece * 2:i * 4 + piece * 2 + 2]:
                    self._show(item, visible)
                    if visible:
                        self.canvas.coords(item, *segments[piece])
        self.dirty = False
