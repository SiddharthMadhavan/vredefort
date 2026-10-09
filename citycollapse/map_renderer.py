"""Native raster map. Workers return Pillow images; Tk objects stay on the UI thread."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
from io import BytesIO
import math
from pathlib import Path
import time
import urllib.request
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from .data import ROOT
from .geometry import project, unproject

FONT_FILE = ROOT / 'assets/fonts/VT323-Regular.ttf'

@dataclass(frozen=True)
class Camera:
    x: float
    y: float
    zoom: int
    width: int
    height: int

    @property
    def scale(self):
        return 256 * 2 ** self.zoom

    def screen(self, point):
        return (point[0] - self.x) * self.scale + self.width / 2, (point[1] - self.y) * self.scale + self.height / 2

    def world(self, x, y):
        return self.x + (x - self.width / 2) / self.scale, self.y + (y - self.height / 2) / self.scale

    @property
    def bounds(self):
        return *self.world(0, 0), *self.world(self.width, self.height)

    def tile_keys(self):
        left, top, right, bottom = self.bounds
        count = 2 ** self.zoom
        return [(self.zoom, x, y) for x in range(max(0, math.floor(left * count)), min(count, math.floor(right * count) + 1)) for y in range(max(0, math.floor(top * count)), min(count, math.floor(bottom * count) + 1))]

class TileCache:
    def __init__(self, url):
        self.url = url
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='map-io')
        self.pending, self.failed = {}, {}
        self.images = OrderedDict()
        self.folder = ROOT / '.cache/tiles' / hashlib.sha256(url.encode()).hexdigest()[:16]

    def download(self, key):
        z, x, y = key
        path = self.folder / str(z) / str(x) / f'{y}.png'
        if path.exists():
            try:
                with Image.open(path) as image:
                    return image.convert('RGB').resize((256, 256))
            except OSError:
                pass
        request = urllib.request.Request(self.url.format(z=z, x=x, y=y), headers={'User-Agent': 'CityCollapse-desktop/1.0'})
        with urllib.request.urlopen(request, timeout=6) as response:
            payload = response.read(2_000_001)
        if len(payload) > 2_000_000:
            raise ValueError('Oversized map tile')
        with Image.open(BytesIO(payload)) as image:
            tile = image.convert('RGB').resize((256, 256))
        path.parent.mkdir(parents=True, exist_ok=True)
        tile.save(path)
        return tile

    def request(self, keys):
        now = time.monotonic()
        for key in keys:
            if key not in self.images and key not in self.pending and now - self.failed.get(key, -math.inf) >= 30 and len(self.pending) < 24:
                self.pending[key] = self.pool.submit(self.download, key)

    def poll(self):
        changed = False
        for key, future in list(self.pending.items()):
            if not future.done():
                continue
            del self.pending[key]
            try:
                self.images[key] = future.result()
                self.failed.pop(key, None)
                while len(self.images) > 256:
                    self.images.popitem(last=False)
            except Exception:
                self.failed[key] = time.monotonic()
            changed = True
        return changed

    def snapshot(self, keys):
        return {key: self.images[key] for key in keys if key in self.images}

    def retry(self):
        self.failed.clear()

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)

def width_style(properties, field, statistics):
    low, high = statistics[field]['min'], statistics[field]['max']
    value = properties.get(field)
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return '#68716d', 1.0
    fraction = max(0, min(1, (value - low) / (high - low)))
    stops = [(0, (138, 146, 144)), (.25, (114, 132, 121)), (.5, (86, 111, 96)), (1, (52, 75, 60))]
    for (start, a), (end, b) in zip(stops, stops[1:]):
        if fraction <= end:
            ratio = (fraction - start) / (end - start)
            return tuple(round(x + (y - x) * ratio) for x, y in zip(a, b)), 1 + .35 * fraction
    return stops[-1][1], 1.35

def paint_map(camera, tiles, datasets, mode, field, roads_on, hospitals_on, fire_on, selected):
    image = Image.new('RGB', (camera.width, camera.height), '#0b100d')
    draw = ImageDraw.Draw(image)
    for z, x, y in camera.tile_keys():
        sx, sy = camera.screen((x / 2 ** z, y / 2 ** z))
        tile = tiles.get((z, x, y))
        if tile is not None:
            image.paste(tile, (round(sx), round(sy)))
        else:
            draw.rectangle((sx, sy, sx + 255, sy + 255), outline='#18251d')
    view = datasets['views'][mode]
    if roads_on:
        indices = view['index'].query(camera.bounds)
        if mode == 'KML width shading':
            indices = sorted(indices, key=lambda i: view['roads'][i].properties.get(field, 0) or 0)
        for index in indices:
            road = view['roads'][index]
            if selected and road.id != selected:
                continue
            if mode == 'KML width shading':
                color, factor = width_style(road.properties, field, datasets['width_metadata']['widthFields'])
                base = 1.5 + max(0, min(8, camera.zoom - 10)) * .56
            else:
                color, factor, base = '#33453a' if mode == 'Traffic simulation' else '#7eac85', 1, 1.5 + max(0, camera.zoom - 10) * .7
            for path in road.paths:
                screen = [camera.screen(point) for point in path]
                # Skip sub-pixel intermediate vertices for painting only, never change saved data.
                points = [screen[0]]
                for point in screen[1:-1]:
                    if abs(point[0] - points[-1][0]) + abs(point[1] - points[-1][1]) >= 1:
                        points.append(point)
                points.append(screen[-1])
                draw.line(points, fill=color, width=max(1, round(base * factor)), joint='curve')
        if selected and mode != 'KML width shading':
            road = view['by_id'][selected]
            for point in (road.paths[0][0], road.paths[-1][-1]):
                x, y = camera.screen(point)
                draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill='#70b67a', outline='#c4e5c4', width=1)
    font = ImageFont.truetype(str(FONT_FILE), 16) if FONT_FILE.exists() else ImageFont.load_default()
    for kind, enabled in [('hospitals', hospitals_on), ('fire', fire_on)]:
        if not enabled:
            continue
        for point in datasets[kind]:
            x, y = camera.screen(point['point'])
            if -10 <= x <= camera.width + 10 and -10 <= y <= camera.height + 10:
                fill, outline = ('#132d20', '#a4c9a7') if kind == 'hospitals' else ('#2c2517', '#cba96e')
                draw.rectangle((x - 7, y - 7, x + 7, y + 7), fill=fill, outline=outline)
                if kind == 'hospitals':
                    draw.line((x - 4, y, x + 4, y), fill='#c7efca', width=1)
                    draw.line((x, y - 4, x, y + 4), fill='#c7efca', width=1)
                else:
                    draw.text((x, y + 1), 'F', fill='#e6c48a', font=font, anchor='mm')
    return image

def paint_cars(camera, vehicles):
    image = Image.new('RGBA', (camera.width, camera.height))
    draw = ImageDraw.Draw(image)
    hits = []
    for vehicle in vehicles:
        coordinate, bearing = vehicle.position()
        x, y = camera.screen(project(*coordinate))
        if -20 <= x <= camera.width + 20 and -20 <= y <= camera.height + 20:
            hits.append((x, y, vehicle))
            angle = math.radians(bearing)
            def rotate(dx, dy):
                return round(x + dx * math.cos(angle) - dy * math.sin(angle)), round(y + dx * math.sin(angle) + dy * math.cos(angle))
            draw.polygon([rotate(-5, -9), rotate(5, -9), rotate(5, 9), rotate(-5, 9)], fill='#b0e1a1', outline='#07120d')
            draw.polygon([rotate(-3, -5), rotate(3, -5), rotate(3, -1), rotate(-3, -1)], fill='#234c35')
            draw.polygon([rotate(-3, 3), rotate(3, 3), rotate(3, 6), rotate(-3, 6)], fill='#234c35')
    return image, hits


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

    def paint(self, camera, view, result, selected=None):
        if camera != self.camera or view is not self.view:
            self.paths = traffic_paths(camera, view)
            self.camera, self.view = camera, view
        return paint_traffic(camera, view, result, selected, self.paths)

    def frame(self, camera, view, result, selected=None):
        from .traffic_animation import prepare_flow_paths
        image = self.paint(camera, view, result, selected=selected)
        return image, prepare_flow_paths(camera, self.paths, result)


def paint_traffic(camera, view, result, selected=None, geometry=None):
    """Transparent traffic layer; no Tk objects or mutation of model results."""
    image = Image.new('RGBA', (camera.width, camera.height))
    glow = Image.new('RGBA', image.size)
    glow_draw, draw = ImageDraw.Draw(glow), ImageDraw.Draw(image)
    paths, markers = [], []
    base = max(2, min(6, 2 + (camera.zoom - 11) * .5))
    for identifier, points in geometry if geometry is not None else traffic_paths(camera, view):
        state = result.links[identifier]
        severity = state.congestion
        color = traffic_color(severity)
        if state.closed:
            paths.append((identifier, points, (104, 66, 68, 200), round(base)))
            markers.append(points[len(points) // 2])
        else:
            width = round(base + severity)
            alpha = round(24 + 105 * severity)
            glow_draw.line(points, fill=(*color, alpha), width=width + 5 + round(5 * severity), joint='curve')
            paths.append((identifier, points, (*color, 220), width))
    image = Image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(3)), image)
    draw = ImageDraw.Draw(image)
    for identifier, points, color, width in paths:
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
