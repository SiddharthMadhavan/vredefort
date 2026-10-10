"""Offline maps must remain useful without ever contacting the tile server."""
from concurrent.futures import Future
from contextlib import closing
from io import BytesIO
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from PIL import Image
from vredefort.map_renderer import TileCache
from vredefort import config


URL = 'https://tiles.example/{z}/{x}/{y}.png'


def png(color):
    stream = BytesIO()
    Image.new('RGB', (256, 256), color).save(stream, format='PNG')
    return stream.getvalue()


class MapCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def cache(self, **kwargs):
        cache = TileCache(URL, cache_dir=self.folder, **kwargs)
        self.addCleanup(lambda: cache.pool.shutdown(wait=True, cancel_futures=True))
        return cache

    def settle(self, cache, keys):
        cache.request(keys)
        deadline = time.monotonic() + 3
        while cache.pending and time.monotonic() < deadline:
            cache.poll()
            time.sleep(.005)
        self.assertFalse(cache.pending)
        return cache.snapshot(keys)

    def store(self, key, image):
        z, x, y = key
        path = self.folder / str(z) / str(x) / f'{y}.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)

    def make_pack(self, format='png'):
        path = self.folder / 'map.mbtiles'
        with closing(sqlite3.connect(path)) as db:
            db.executescript('CREATE TABLE metadata(name TEXT, value TEXT); '
                'CREATE TABLE tiles(zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB); '
                'CREATE UNIQUE INDEX tile_index ON tiles(zoom_level,tile_column,tile_row);')
            db.executemany('INSERT INTO metadata VALUES(?,?)', [('format', format),
                ('attribution', '<a href="https://example.com">Map provider</a>')])
            # XYZ 3/2/5 => TMS row 2. A second row detects incorrect inversion.
            db.executemany('INSERT INTO tiles VALUES(?,?,?,?)', [(3, 2, 2, png('green')),
                (3, 2, 5, png('red'))])
            db.commit()
        return path

    def test_cached_native_tile_survives_restart_without_network(self):
        self.store((3, 2, 5), Image.new('RGB', (256, 256), 'green'))
        with patch('urllib.request.urlopen', side_effect=AssertionError('unexpected HTTP')):
            cache = self.cache(offline=True)
            self.assertEqual(self.settle(cache, [(3, 2, 5)])[(3, 2, 5)].getpixel((20, 20)), (0, 128, 0))
            cache.close()
            reopened = self.cache(offline=True)
            self.assertIn((3, 2, 5), self.settle(reopened, [(3, 2, 5)]))

    def test_offline_zoom_uses_correct_parent_quadrant_without_writing_fake_native_tile(self):
        tile = Image.new('RGB', (256, 256), 'red')
        tile.paste(Image.new('RGB', (128, 128), 'blue'), (128, 128))
        self.store((2, 1, 1), tile)
        with patch('urllib.request.urlopen', side_effect=AssertionError('unexpected HTTP')):
            cache = self.cache(offline=True)
            snapshot = self.settle(cache, [(3, 3, 3)])
            self.assertEqual(snapshot[(3, 3, 3)].getpixel((128, 128)), (0, 0, 255))
            self.assertIn((3, 3, 3), cache.fallback_keys)
            self.assertFalse((self.folder / '3/3/3.png').exists())

    def test_missing_offline_tile_is_reported_and_only_retried_explicitly(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('unexpected HTTP')) as http:
            cache = self.cache(offline=True)
            self.assertEqual(self.settle(cache, [(3, 2, 5)]), {})
            self.assertIn((3, 2, 5), cache.failed)
            cache.failed[(3, 2, 5)] = 0
            cache.request([(3, 2, 5)])
            self.assertFalse(cache.pending)
            self.store((3, 2, 5), Image.new('RGB', (256, 256), 'green'))
            cache.retry()
            self.assertIn((3, 2, 5), self.settle(cache, [(3, 2, 5)]))
            http.assert_not_called()

    def test_raster_mbtiles_is_read_only_and_uses_tms_rows(self):
        pack = self.make_pack()
        before = pack.read_bytes()
        with patch('urllib.request.urlopen', side_effect=AssertionError('unexpected HTTP')):
            cache = self.cache(local_path=pack)
            self.assertTrue(cache.offline)
            self.assertEqual(cache.attribution, 'Map provider')
            tile = self.settle(cache, [(3, 2, 5)])[(3, 2, 5)]
            self.assertEqual(tile.getpixel((20, 20)), (0, 128, 0))
            self.assertEqual(pack.read_bytes(), before)

    def test_local_xyz_directory_and_parent_tiles(self):
        self.store((3, 2, 5), Image.new('RGB', (256, 256), 'green'))
        with patch('urllib.request.urlopen', side_effect=AssertionError('unexpected HTTP')):
            cache = self.cache(local_path=self.folder)
            self.assertIn((4, 4, 10), self.settle(cache, [(4, 4, 10)]))
            self.assertIn((4, 4, 10), cache.fallback_keys)

    def test_rejects_vector_or_missing_map_pack(self):
        with self.assertRaisesRegex(ValueError, 'vector'):
            TileCache(URL, local_path=self.make_pack('pbf'))
        with self.assertRaisesRegex(ValueError, 'does not exist'):
            TileCache(URL, local_path=self.folder / 'missing.mbtiles')

    def test_online_cache_reuses_disk_and_recovers_corrupt_tile(self):
        self.store((3, 2, 5), Image.new('RGB', (256, 256), 'green'))
        damaged = self.folder / '3/2/5.png'
        damaged.write_bytes(b'corrupted')
        with patch('urllib.request.urlopen', return_value=BytesIO(png('blue'))) as http:
            cache = self.cache()
            self.assertEqual(self.settle(cache, [(3, 2, 5)])[(3, 2, 5)].getpixel((0, 0)), (0, 0, 255))
            self.assertEqual(http.call_count, 1)
        with patch('urllib.request.urlopen', side_effect=AssertionError('unexpected HTTP')):
            reopened = self.cache()
            self.assertIn((3, 2, 5), self.settle(reopened, [(3, 2, 5)]))

    def test_visible_tile_access_keeps_lru_entry_and_reports_only_changed_tiles(self):
        cache = self.cache(offline=True)
        cache.MAX_IMAGES = 2
        cache.images[(1, 0, 0)] = Image.new('RGB', (256, 256))
        cache.images[(1, 1, 0)] = Image.new('RGB', (256, 256))
        cache.snapshot([(1, 0, 0)])
        completed = Future()
        completed.set_result((Image.new('RGB', (256, 256)), False))
        cache.pending[(1, 0, 1)] = completed
        cache.poll()
        self.assertIn((1, 0, 0), cache.images)
        self.assertNotIn((1, 1, 0), cache.images)
        self.assertEqual(cache.changed_keys, {(1, 0, 1)})
        cache.poll()
        self.assertFalse(cache.changed_keys)

    def test_saved_map_choice_and_environment_override(self):
        preferences = self.folder / 'preferences.json'
        with patch.object(config, 'MAP_PREFERENCES', preferences), patch.object(config, 'environment_values', return_value={}):
            config.save_map_preferences(True, self.folder / 'map.mbtiles')
            self.assertTrue(config.settings()['offline'])
            self.assertEqual(config.settings()['local_path'], str(self.folder / 'map.mbtiles'))
            with patch.object(config, 'environment_values', return_value={'VREDEFORT_MAP_OFFLINE': 'false', 'VREDEFORT_MAP_PATH': ''}):
                self.assertFalse(config.settings()['offline'])
                self.assertIsNone(config.settings()['local_path'])

    def test_pan_cancels_queued_tiles_but_preserves_other_visible_window(self):
        cache = self.cache(offline=True)
        with patch.object(cache.pool, 'submit', side_effect=lambda *args: Future()):
            cache.request([(4, 0, 0)])
            stale = cache.pending[(4, 0, 0)]
            cache.request([(4, 2, 2)], viewer='comparison')
            comparison = cache.pending[(4, 2, 2)]
            cache.request([(4, 1, 1)])
            self.assertTrue(stale.cancelled())
            self.assertNotIn((4, 0, 0), cache.pending)
            self.assertFalse(comparison.cancelled())
            self.assertIn((4, 1, 1), cache.pending)


if __name__ == '__main__':
    unittest.main()
