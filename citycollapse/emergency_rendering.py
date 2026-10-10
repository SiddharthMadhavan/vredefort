"""Bounded emergency accessibility highlights on the simulation map."""
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from .emergency_services import COLORS
from .map_renderer import FONT_FILE
import math


def trim_paths(paths, start, end):
    """Crop by arc-length fraction, preserving bends and separate geometry parts."""
    length = sum(math.dist(a, b) for path in paths for a, b in zip(path, path[1:]))
    low, high = min(start, end) * length, max(start, end) * length
    travelled, pieces = 0., []
    for path in paths:
        points = []
        for a, b in zip(path, path[1:]):
            distance = math.dist(a, b)
            if distance and travelled < high and travelled + distance > low:
                t0 = max(0., (low - travelled) / distance)
                t1 = min(1., (high - travelled) / distance)
                first = (a[0] + t0 * (b[0] - a[0]), a[1] + t0 * (b[1] - a[1]))
                last = (a[0] + t1 * (b[0] - a[0]), a[1] + t1 * (b[1] - a[1]))
                if not points or first != points[-1]:
                    points.append(first)
                points.append(last)
            travelled += distance
        if points:
            pieces.append(tuple(points))
    return tuple(pieces) if start <= end else tuple(tuple(reversed(path)) for path in reversed(pieces))


def route_paths(network, route):
    paths = []
    for leg in route.legs:
        road = network.roads_by_id[leg.edge_id]
        geometry = road.paths
        source = network.nodes_by_id[road.properties['source']]['point']
        if math.dist(geometry[0][0], source) > math.dist(geometry[-1][-1], source):
            geometry = tuple(tuple(reversed(path)) for path in reversed(geometry))
        paths.extend(trim_paths(geometry, leg.start_fraction, leg.end_fraction))
    return tuple(paths)


def paint_emergency_route(image, camera, network, route):
    paths = route_paths(network, route)
    draw = ImageDraw.Draw(image)
    for path in paths:
        screen = camera.screen_path(path)
        draw.line(screen, fill='#092d36', width=11, joint='curve')
        draw.line(screen, fill='#63efff', width=6, joint='curve')
        draw.line(screen, fill='#daffff', width=2, joint='curve')
        # Direction chevrons follow the actual polyline toward the junction.
        remaining = 65.
        for a, b in zip(screen, screen[1:]):
            distance = math.dist(a, b)
            if not distance:
                continue
            ux, uy = (b[0] - a[0]) / distance, (b[1] - a[1]) / distance
            while remaining <= distance:
                x, y = a[0] + remaining * ux, a[1] + remaining * uy
                if 0 <= x <= camera.width and 0 <= y <= camera.height:
                    draw.line(((x - ux * 7 - uy * 4, y - uy * 7 + ux * 4), (x, y),
                               (x - ux * 7 + uy * 4, y - uy * 7 - ux * 4)), fill='#ffffff', width=2)
                remaining += 110
            remaining -= distance
    # This is a coordinate snap, not a surveyed driveway or routable connector.
    origin = camera.screen(route.facility.point)
    road_start = camera.screen(paths[0][0]) if paths else camera.screen(route.point)
    distance = math.dist(origin, road_start)
    if distance:
        for offset in range(0, math.ceil(distance), 10):
            end = min(distance, offset + 4)
            draw.line(tuple((origin[0] + t / distance * (road_start[0] - origin[0]),
                             origin[1] + t / distance * (road_start[1] - origin[1])) for t in (offset, end)),
                      fill='#63efff', width=2)
    for world, label in ((route.facility.point, 'H' if route.facility.kind == 'hospitals' else 'F'),
                         (route.point, 'J')):
        x, y = camera.screen(world)
        draw.ellipse((x - 11, y - 11, x + 11, y + 11), fill='#102b30', outline='#63efff', width=3)
        font = ImageFont.truetype(str(FONT_FILE), 18) if FONT_FILE.exists() else ImageFont.load_default()
        draw.text((x - 4, y - 8), label, font=font, fill='#ffffff')


def visible_risks(camera, report, kind=None):
    # One highest-priority junction per 24px cell keeps the city view readable.
    # The report/panel retain every junction, including existing coverage gaps.
    cells = set()
    markers = []
    for point in report.risks(kind):
        x, y = camera.screen(point.point)
        if not (-12 <= x <= camera.width + 12 and -12 <= y <= camera.height + 12):
            continue
        cell = int(x // 24), int(y // 24)
        if cell in cells:
            continue
        cells.add(cell)
        markers.append((x, y, point))
    return tuple(markers)


def paint_emergency(image, camera, report, kind=None):
    marks = visible_risks(camera, report, kind)
    glow = Image.new('RGBA', image.size)
    draw = ImageDraw.Draw(glow)
    for x, y, point in marks:
        color = COLORS[point.status]
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=color + '70')
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(5)))
    draw = ImageDraw.Draw(image)
    for x, y, point in marks:
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=COLORS[point.status] + 'e0', outline='#101a16', width=1)
        if point.status == 'lost':
            draw.ellipse((x - 7, y - 7, x + 7, y + 7), outline=COLORS[point.status], width=2)
    font = ImageFont.truetype(str(FONT_FILE), 17) if FONT_FILE.exists() else ImageFont.load_default()
    for anchor in report.anchors:
        if kind and anchor.kind != kind:
            continue
        x, y = camera.screen(anchor.point)
        if -12 <= x <= camera.width + 12 and -12 <= y <= camera.height + 12:
            draw.rectangle((x - 7, y - 9, x + 7, y + 9), fill='#11221ef0', outline='#9bdcd5', width=1)
            draw.text((x - 4, y - 8), 'F' if anchor.kind == 'fire' else 'H', font=font, fill='#9bdcd5')
