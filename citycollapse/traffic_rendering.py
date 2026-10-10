import math
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from .map_renderer import FONT_FILE

def traffic_color(congestion):
    """Green -> amber -> red, with a continuous and bounded palette."""
    value = max(0.0, min(1.0, congestion))
    a, b, fraction = ((61, 215, 108), (242, 197, 58), value * 2) if value <= .5 else ((242, 197, 58), (248, 62, 66), (value - .5) * 2)
    return tuple(round(x + (y - x) * fraction) for x, y in zip(a, b))


def traffic_paths(camera, view):
    """Project/simplify paths only when the viewport changes."""
    paths = []
    for index in sorted(view['index'].query(camera.bounds)):
        road = view['roads'][index]
        for path in road.paths:
            screen = camera.screen_path(path)
            points = [screen[0]]
            for point in screen[1:-1]:
                if abs(point[0] - points[-1][0]) + abs(point[1] - points[-1][1]) >= 1.5:
                    points.append(point)
            points.append(screen[-1])
            paths.append((road.id, tuple(points)))
    return tuple(paths)


class TrafficPainter:
    """Paint static glow only on state/camera changes; motion uses native lines."""
    def __init__(self):
        self.camera, self.view, self.paths = None, None, ()

    def paint(self, camera, view, result, selected=None, impact=None, heatmap=False):
        if camera != self.camera or view is not self.view:
            self.paths = traffic_paths(camera, view)
            self.camera, self.view = camera, view
        return paint_traffic(camera, view, result, selected, self.paths, impact, heatmap)

    def frame(self, camera, view, result, selected=None, impact=None, diversion=None, datasets=None, heatmap=False,
              emergency=None, emergency_kind=None):
        from .traffic_animation import prepare_flow_paths
        image = self.paint(camera, view, result, selected=selected, impact=impact, heatmap=heatmap)
        if impact and impact.closed_roads:
            paint_impacts(image, camera, view, self.paths, impact, diversion, datasets, result.blocked_nodes)
        if emergency is not None:
            from .emergency_rendering import paint_emergency
            paint_emergency(image, camera, emergency, emergency_kind)
        return image, prepare_flow_paths(camera, self.paths, result)


def congestion_hotspots(camera, geometry, result):
    """Group visible high-congestion road samples into bounded display circles.

    The 70% threshold uses the scenario's congestion fraction. These screen
    regions are visual highlights, not measured queue boundaries. Uniform
    distance sampling avoids interpreting extra polyline vertices as traffic.
    """
    from .traffic_animation import visible_paths, FlowPath, point_at
    samples = []
    bounds = (-24, -24, camera.width + 24, camera.height + 24)
    for identifier, points in geometry:
        state = result.links[identifier]
        if state.closed or state.flow <= 0 or state.congestion < .7:
            continue
        for visible in visible_paths(points, bounds):
            distances = [0.]
            for a, b in zip(visible, visible[1:]):
                distances.append(distances[-1] + math.dist(a, b))
            length = distances[-1]
            count = max(1, math.ceil(length / 100))
            path = FlowPath(identifier, visible, tuple(distances), 0, state.congestion)
            for i in range(count):
                x, y = point_at(path, length * (i + .5) / count)
                samples.append((x, y, state.congestion, identifier))
    samples.sort(key=lambda item: (-item[2], item[3], item[0], item[1]))
    circles = []
    while samples and len(circles) < 12:
        seed = samples[0]
        nearby, remaining = [], []
        for sample in samples:
            (nearby if math.dist(sample[:2], seed[:2]) <= 65 else remaining).append(sample)
        weight = sum(item[2] for item in nearby)
        x = sum(item[0] * item[2] for item in nearby) / weight
        y = sum(item[1] * item[2] for item in nearby) / weight
        radius = max(38., max(math.dist((x, y), item[:2]) for item in nearby) + 22)
        circles.append((x, y, radius, max(item[2] for item in nearby)))
        samples = remaining
    return circles


def paint_hotspot_circles(image, circles):
    if not circles:
        return image
    halo, borders = Image.new('RGBA', image.size), Image.new('RGBA', image.size)
    glow_draw, draw = ImageDraw.Draw(halo), ImageDraw.Draw(borders)
    for x, y, radius, severity in circles:
        color = traffic_color(severity)
        bounds = (x - radius, y - radius, x + radius, y + radius)
        glow_draw.ellipse(bounds, outline=(*color, 155), width=9)
        draw.ellipse(bounds, fill=(*color, 12), outline=(*color, 205), width=2)
    image = Image.alpha_composite(image, halo.filter(ImageFilter.GaussianBlur(5)))
    return Image.alpha_composite(image, borders)


def paint_heatmap(camera, geometry, result):
    """Soften simulated road congestion into a proximity overlay, not new data.

    Render at quarter resolution to keep blur work off the animation loop.
    A road contributes along its polyline, independent of vertex density.
    Higher congestion takes priority at overlaps; this is not a vehicle count.
    Closed roads have no flow and contribute no heat; closure markers are
    painted separately above this layer.
    """
    scale = 4
    size = (max(1, math.ceil(camera.width / scale)), max(1, math.ceil(camera.height / scale)))
    image = Image.new('RGBA', size)
    draw = ImageDraw.Draw(image)
    for identifier, points in sorted(geometry, key=lambda entry: result.links[entry[0]].congestion):
        state = result.links[identifier]
        if state.closed or state.flow <= 0:
            continue
        severity = max(0., min(1., state.congestion))
        color = traffic_color(severity)
        draw.line([(x / scale, y / scale) for x, y in points],
                  fill=(*color, round(50 + severity * 100)), width=13, joint='curve')
    image = image.filter(ImageFilter.GaussianBlur(4)).resize(
        (camera.width, camera.height), Image.Resampling.BILINEAR)
    return paint_hotspot_circles(image, congestion_hotspots(camera, geometry, result))


def paint_traffic(camera, view, result, selected=None, geometry=None, impact=None, heatmap=False):
    """Transparent traffic layer; no Tk objects or mutation of model results."""
    geometry = geometry if geometry is not None else traffic_paths(camera, view)
    image = paint_heatmap(camera, geometry, result) if heatmap else Image.new('RGBA', (camera.width, camera.height))
    glow = Image.new('RGBA', image.size)
    glow_draw, draw = ImageDraw.Draw(glow), ImageDraw.Draw(image)
    paths, markers = [], []
    base = max(2, min(6, 2 + (camera.zoom - 11) * .5))
    show_impacts = impact is not None and bool(impact.closed_roads)
    selected_ids = {selected} if isinstance(selected, str) else set(selected or ())
    for identifier, points in geometry:
        state = result.links[identifier]
        severity = state.congestion
        color = traffic_color(severity)
        if state.closed:
            paths.append((identifier, points, (200, 72, 72, 230), max(3, round(base))))
            markers.append(points[len(points) // 2])
        else:
            width = round(base + severity)
            affected = not show_impacts or identifier in impact.affected_roads
            alpha = round((24 + 105 * severity) * (1 if affected else .2))
            glow_draw.line(points, fill=(*color, alpha), width=width + 5 + round(5 * severity), joint='curve')
            paths.append((identifier, points, (*color, 220 if affected else 70), width))
    image = Image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(3)), image)
    draw = ImageDraw.Draw(image)
    for identifier, points, color, width in paths:
        if show_impacts and identifier in impact.loaded_roads:
            draw.line(points, fill='#dfac57', width=width + 3, joint='curve')
        if identifier in selected_ids:
            draw.line(points, fill='#d7eddc', width=width + 3, joint='curve')
        draw.line(points, fill=color, width=max(1, width), joint='curve')
    for x, y in markers:
        draw.line((x - 4, y - 4, x + 4, y + 4), fill='#ff7272', width=2)
        draw.line((x - 4, y + 4, x + 4, y - 4), fill='#ff7272', width=2)
    for node in view['nodes']:
        if node['id'] in result.blocked_nodes:
            x, y = camera.screen(node['point'])
            draw.rectangle((x - 6, y - 6, x + 6, y + 6), fill='#3b1519', outline='#ff7272', width=2)
    return image


def paint_impacts(image, camera, view, geometry, report, diversion, datasets, blocked_nodes=frozenset()):
    from .traffic_animation import visible_paths, FlowPath, path_slice
    draw = ImageDraw.Draw(image)
    options = {edge for option in report.diversions for edge in option.route.edge_ids}
    active = set(diversion.route.edge_ids) if diversion else set()
    for identifier, points in geometry:
        if identifier not in options:
            continue
        for visible in visible_paths(points, (-12, -12, camera.width + 12, camera.height + 12)):
            if identifier in active:
                draw.line(visible, fill='#7fe6f0', width=6, joint='curve')
                draw.line(visible, fill='#163f49', width=2, joint='curve')
            else:
                distances = [0.0]
                for a, b in zip(visible, visible[1:]):
                    distances.append(distances[-1] + math.dist(a, b))
                path = FlowPath(identifier, visible, tuple(distances), 0, 0)
                start = 0.0
                while start < path.length:
                    coords = path_slice(path, start, min(path.length, start + 8))
                    draw.line(tuple(zip(coords[::2], coords[1::2])), fill='#438eac', width=2, joint='curve')
                    start += 15
    for node in view['nodes']:
        if node['id'] in report.affected_nodes and node['id'] not in blocked_nodes:
            x, y = camera.screen(node['point'])
            if -6 <= x <= camera.width + 6 and -6 <= y <= camera.height + 6:
                draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill='#e6b669')
    # Facilities remain visible as affected markers even if their general layer
    # is hidden. Their original coordinates and interactive details are retained.
    if datasets:
        font = ImageFont.truetype(str(FONT_FILE), 16) if FONT_FILE.exists() else ImageFont.load_default()
        for facility in report.facilities:
            point = datasets[facility.kind][facility.index]
            x, y = camera.screen(point['point'])
            if -16 <= x <= camera.width + 16 and -16 <= y <= camera.height + 16:
                draw.ellipse((x - 12, y - 12, x + 12, y + 12), outline='#efb65f', width=2)
                draw.rectangle((x - 7, y - 7, x + 7, y + 7), fill='#14251a', outline='#efb65f')
                if facility.kind == 'hospitals':
                    draw.line((x - 4, y, x + 4, y), fill='#d4e8d4')
                    draw.line((x, y - 4, x, y + 4), fill='#d4e8d4')
                else:
                    draw.text((x, y + 1), 'F', fill='#efb65f', font=font, anchor='mm')
