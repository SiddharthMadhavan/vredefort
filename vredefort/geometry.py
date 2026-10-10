"""Web Mercator map coordinates and road geometry, independent of the GUI."""
import math

def project(lon: float, lat: float) -> tuple[float, float]:
    lat = max(-85.05112878, min(85.05112878, lat))
    return (lon + 180) / 360, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2

def unproject(x: float, y: float) -> tuple[float, float]:
    return x * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y))))

def line_distance_squared(x, y, points):
    best = math.inf
    for a, b in zip(points, points[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        denominator = dx * dx + dy * dy
        t = max(0, min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / denominator)) if denominator else 0
        best = min(best, (x - a[0] - t * dx) ** 2 + (y - a[1] - t * dy) ** 2)
    return best
