"""Native raster map. Workers return Pillow images; Tk objects stay on the UI thread."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
from io import BytesIO
import math
import time
import urllib.request
from PIL import Image
from .data import ROOT

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
