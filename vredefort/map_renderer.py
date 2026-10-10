"""Native raster map. Workers return Pillow images; Tk objects stay on the UI thread."""
from collections import OrderedDict
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import html
from io import BytesIO
import math
import re
from pathlib import Path
import sqlite3
import time
import urllib.request
from urllib.parse import urlsplit
from PIL import Image
from .data import ROOT
from .paths import CACHE_DIR

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

    def screen_path(self, points):
        """Hoist camera arithmetic out of the per-vertex drawing loop."""
        scale, x, y = self.scale, self.x, self.y
        half_width, half_height = self.width / 2, self.height / 2
        return [((px - x) * scale + half_width, (py - y) * scale + half_height)
                for px, py in points]

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
    """On-demand disk cache, or a read-only local XYZ/raster MBTiles source.

    Offline misses can use a lower-resolution parent tile. They never trigger
    HTTP requests or get saved as native-resolution tiles.
    """
    MAX_IMAGES = 256

    def __init__(self, url, *, offline=False, local_path=None, cache_dir=None):
        self.url = url
        self.local_path = Path(local_path).expanduser().resolve() if local_path else None
        self.offline = offline or self.local_path is not None
        self.attribution = None
        self.mbtiles = False
        if self.local_path:
            if not self.local_path.exists():
                raise ValueError('Local basemap does not exist')
            self.mbtiles = self.local_path.is_file()
            if self.mbtiles:
                if self.local_path.suffix.lower() != '.mbtiles':
                    raise ValueError('Choose a raster .mbtiles file or an XYZ tile directory')
                try:
                    with closing(self._database()) as db:
                        metadata = dict(db.execute('SELECT name, value FROM metadata'))
                        db.execute('SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles LIMIT 1')
                    if metadata.get('format', '').lower() not in ('png', 'jpg', 'jpeg', 'webp'):
                        raise ValueError('This map pack contains vector tiles. Use PNG/JPEG/WebP raster MBTiles.')
                    self.attribution = html.unescape(re.sub(r'<[^>]*>', '', metadata.get('attribution', ''))) or None
                except sqlite3.Error as error:
                    raise ValueError('Invalid raster MBTiles map pack') from error
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='map-io')
        self.pending, self.failed = {}, {}
        self.views = {}
        self.images = OrderedDict()
        self.changed_keys, self.fallback_keys = set(), set()
        self.folder = Path(cache_dir) if cache_dir else CACHE_DIR / 'tiles' / hashlib.sha256(url.encode()).hexdigest()[:16]

    def _database(self):
        # A connection per worker operation: sqlite connections are not shared
        # between the Tk thread and the tile-loading threads.
        return sqlite3.connect(self.local_path.as_uri() + '?mode=ro', uri=True)

    @staticmethod
    def _decode(source):
        with Image.open(source) as image:
            tile = image.convert('RGB')
            return tile if tile.size == (256, 256) else tile.resize((256, 256))

    def _local(self, key, db=None):
        z, x, y = key
        if db is not None:
            # MBTiles stores TMS rows; the application camera uses XYZ rows.
            row = db.execute('SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?',
                             (z, x, (1 << z) - 1 - y)).fetchone()
            return self._decode(BytesIO(row[0])) if row else None
        folder = self.local_path or self.folder
        suffixes = ('png', 'jpg', 'jpeg', 'webp') if self.local_path else ('png',)
        for suffix in suffixes:
            path = folder / str(z) / str(x) / f'{y}.{suffix}'
            if path.exists():
                # CARTO permits device caching for up to 30 days.
                host = urlsplit(self.url).hostname or ''
                if not self.local_path and host.endswith('basemaps.cartocdn.com') and time.time() - path.stat().st_mtime >= 30 * 86400:
                    continue
                try:
                    return self._decode(path)
                except OSError:
                    continue
        return None

    def download(self, key):
        z, x, y = key
        path = self.folder / str(z) / str(x) / f'{y}.png'
        db = self._database() if self.mbtiles else None
        try:
            tile = self._local(key, db)
            if tile is not None:
                return tile, False
            if self.offline:
                for parent_zoom in range(z - 1, max(-1, z - 8), -1):
                    factor = 1 << (z - parent_zoom)
                    parent = self._local((parent_zoom, x // factor, y // factor), db)
                    if parent is not None:
                        size = 256 / factor
                        left, top = (x % factor) * size, (y % factor) * size
                        tile = parent.resize((256, 256), Image.Resampling.BILINEAR,
                                             box=(left, top, left + size, top + size))
                        return tile, True
                raise FileNotFoundError('No local tile covering this view')
        finally:
            if db is not None:
                db.close()
        request = urllib.request.Request(self.url.format(z=z, x=x, y=y), headers={'User-Agent': 'Vredefort-desktop/1.0'})
        with urllib.request.urlopen(request, timeout=6) as response:
            payload = response.read(2_000_001)
        if len(payload) > 2_000_000:
            raise ValueError('Oversized map tile')
        tile = self._decode(BytesIO(payload))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        tile.save(temporary, format='PNG')
        temporary.replace(path)
        return tile, False

    def request(self, keys, *, viewer='main'):
        now = time.monotonic()
        keys = tuple(keys)
        self.views[viewer] = now, keys
        self.views = {name: view for name, view in self.views.items() if now - view[0] < 1}
        visible = {key for _, view_keys in self.views.values() for key in view_keys}
        # Discard queued work after a pan/zoom. In-flight requests finish and
        # remain cached; another visible window's requests are protected.
        for key, future in list(self.pending.items()):
            if key not in visible and future.cancel():
                del self.pending[key]
        if keys:
            cx = sum(key[1] for key in keys) / len(keys)
            cy = sum(key[2] for key in keys) / len(keys)
            keys = sorted(keys, key=lambda key: (key[1] - cx) ** 2 + (key[2] - cy) ** 2)
        for key in keys:
            if key in self.images:
                self.images.move_to_end(key)
            retry = key not in self.failed or (not self.offline and now - self.failed[key] >= 30)
            if key not in self.images and key not in self.pending and retry and len(self.pending) < 24:
                self.pending[key] = self.pool.submit(self.download, key)

    def poll(self):
        changed = False
        self.changed_keys = set()
        for key, future in list(self.pending.items()):
            if not future.done():
                continue
            del self.pending[key]
            try:
                tile, fallback = future.result()
                self.images[key] = tile
                if fallback:
                    self.fallback_keys.add(key)
                self.failed.pop(key, None)
                self.changed_keys.add(key)
                while len(self.images) > self.MAX_IMAGES:
                    evicted, _ = self.images.popitem(last=False)
                    self.fallback_keys.discard(evicted)
            except Exception:
                self.failed[key] = time.monotonic()
            changed = True
        return changed

    def snapshot(self, keys):
        snapshot = {}
        for key in keys:
            if key in self.images:
                self.images.move_to_end(key)
                snapshot[key] = self.images[key]
        return snapshot

    def retry(self):
        self.failed.clear()

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
