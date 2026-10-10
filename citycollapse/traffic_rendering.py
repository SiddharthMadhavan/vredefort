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
            screen = [camera.screen(point) for point in path]
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

    def paint(self, camera, view, result, selected=None, impact=None):
        if camera != self.camera or view is not self.view:
            self.paths = traffic_paths(camera, view)
            self.camera, self.view = camera, view
        return paint_traffic(camera, view, result, selected, self.paths, impact)

    def frame(self, camera, view, result, selected=None, impact=None, diversion=None, datasets=None):
        from .traffic_animation import prepare_flow_paths
        image = self.paint(camera, view, result, selected=selected, impact=impact)
        if impact and impact.closed_roads:
            paint_impacts(image, camera, view, self.paths, impact, diversion, datasets, result.blocked_nodes)
        return image, prepare_flow_paths(camera, self.paths, result)


def paint_traffic(camera, view, result, selected=None, geometry=None, impact=None):
    """Transparent traffic layer; no Tk objects or mutation of model results."""
    image = Image.new('RGBA', (camera.width, camera.height))
    glow = Image.new('RGBA', image.size)
    glow_draw, draw = ImageDraw.Draw(glow), ImageDraw.Draw(image)
    paths, markers = [], []
    base = max(2, min(6, 2 + (camera.zoom - 11) * .5))
    show_impacts = impact is not None and bool(impact.closed_roads)
    for identifier, points in geometry if geometry is not None else traffic_paths(camera, view):
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
        if identifier == selected:
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
