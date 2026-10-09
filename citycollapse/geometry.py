"""Web Mercator map coordinates and road geometry, independent of the GUI."""
import math
from bisect import bisect_right

EARTH_RADIUS_M = 6371008.8

def project(lon: float, lat: float) -> tuple[float, float]:
    lat = max(-85.05112878, min(85.05112878, lat))
    return (lon + 180) / 360, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2

def unproject(x: float, y: float) -> tuple[float, float]:
    return x * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y))))

def distance_metres(a, b) -> float:
    lat1, lat2 = math.radians(a[1]), math.radians(b[1])
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(math.radians(b[0] - a[0]) / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1, h)))

def cumulative_lengths(coordinates) -> tuple[float, ...]:
    result = [0.0]
    for a, b in zip(coordinates, coordinates[1:]):
        result.append(result[-1] + distance_metres(a, b))
    return tuple(result)

def position_along(coordinates, cumulative, distance_m, edge_length_m):
    if not math.isfinite(distance_m) or edge_length_m <= 0 or distance_m < 0 or distance_m > edge_length_m + .01:
        raise ValueError('Distance lies outside the edge')
    total = cumulative[-1]
    if total <= 0:
        raise ValueError('Road has no usable length')
    distance = min(1, distance_m / edge_length_m) * total
    index = min(len(coordinates) - 2, max(0, bisect_right(cumulative, distance) - 1))
    a, b = coordinates[index:index + 2]
    segment = cumulative[index + 1] - cumulative[index]
    fraction = (distance - cumulative[index]) / segment if segment else 0
    lon, lat = a[0] + fraction * (b[0] - a[0]), a[1] + fraction * (b[1] - a[1])
    delta = math.radians(b[0] - a[0])
    bearing = math.degrees(math.atan2(math.sin(delta) * math.cos(math.radians(b[1])), math.cos(math.radians(a[1])) * math.sin(math.radians(b[1])) - math.sin(math.radians(a[1])) * math.cos(math.radians(b[1])) * math.cos(delta))) % 360
    return (lon, lat), bearing

def line_distance_squared(x, y, points):
    best = math.inf
    for a, b in zip(points, points[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        denominator = dx * dx + dy * dy
        t = max(0, min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / denominator)) if denominator else 0
        best = min(best, (x - a[0] - t * dx) ** 2 + (y - a[1] - t * dy) ** 2)
    return best
