"""Native offline source switching, zoom fallback, and paused Tk work budget."""
from contextlib import closing
from dataclasses import replace
from io import BytesIO
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from unittest.mock import patch

from PIL import Image, ImageGrab

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from citycollapse.app import CityCollapseApp
from citycollapse import config


with tempfile.TemporaryDirectory() as temporary, \
        patch.object(config, 'MAP_PREFERENCES', Path(temporary) / 'preferences.json'), \
        patch.dict(os.environ, {'CITYCOLLAPSE_MAP_OFFLINE': 'true', 'CITYCOLLAPSE_MAP_PATH': ''}), \
        patch('urllib.request.urlopen', side_effect=AssertionError('Offline GUI attempted HTTP')) as http:
    app = CityCollapseApp()
    started, stage, failures = time.monotonic(), 'startup', []
    spies = []

    def check():
        global stage, paused_at, pack
        try:
            assert time.monotonic() - started < 70, 'Timeout at ' + stage
            sim = app.simulation
            assert not sim.error, sim.error
            if stage == 'startup':
                if not app.network or not app.map_image or app.tiles.pending:
                    app.after(60, check)
                    return
                assert app.tiles.offline
                app.map_button.invoke()
                assert app.map_options.window.winfo_exists()
                stage = 'options'
                app.after(500, check)
                return
            elif stage == 'options':
                app.map_options.window.update_idletasks()
                assert app.map_options.message.winfo_y() + app.map_options.message.winfo_height() < app.map_options.window.winfo_height()
                Path('.tmp').mkdir(exist_ok=True)
                ImageGrab.grab(window=app.map_options.window.winfo_id()).save('.tmp/map-options-smoke.png')
                # Test-only raster pack: dark background, real local road graph.
                pack = Path(temporary) / 'fixture.mbtiles'
                image = BytesIO()
                Image.new('RGB', (256, 256), '#111a14').save(image, format='PNG')
                with closing(sqlite3.connect(pack)) as db:
                    db.executescript('CREATE TABLE metadata(name TEXT, value TEXT); '
                        'CREATE TABLE tiles(zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB); '
                        'CREATE UNIQUE INDEX tile_index ON tiles(zoom_level,tile_column,tile_row);')
                    db.executemany('INSERT INTO metadata VALUES(?,?)', [('format', 'png'), ('attribution', 'GUI test basemap')])
                    db.executemany('INSERT INTO tiles VALUES(?,?,?,?)', [(z, x, (1 << z) - 1 - y, image.getvalue())
                        for z, x, y in app.camera.tile_keys()])
                    db.commit()
                app.map_options.choose(True, str(pack))
                assert app.tiles.mbtiles and app.attribution.cget('text') == 'GUI test basemap'
                saved = json.loads(config.MAP_PREFERENCES.read_text())
                assert saved['offline'] and saved['local_path'] == str(pack)
                stage = 'pack'
            elif stage == 'pack':
                if app.tiles.pending or app.display_camera != app.camera or app.dirty:
                    app.after(60, check)
                    return
                assert not app.tiles.failed
                old = app.tiles
                app.map_options.choose(True, str(pack.parent / 'missing.mbtiles'))
                assert app.tiles is old
                assert 'does not exist' in app.map_options.message.cget('text')
                app.map_options.window.withdraw()
                app.zoom(1)
                stage = 'zoom'
            elif stage == 'zoom':
                if app.tiles.pending or app.display_camera != app.camera or app.dirty:
                    app.after(60, check)
                    return
                assert app.tiles.fallback_keys and not app.tiles.failed
                assert 'lower-resolution' in app.status.cget('text')
                road = app.network.roads_by_id['kml_merged_e_19725_0_1']
                point = road.paths[0][len(road.paths[0]) // 2]
                app.camera = replace(app.camera, x=point[0], y=point[1], zoom=15)
                app.select_road(road.id)
                app.set_mode('Traffic simulation')
                stage = 'simulation'
            elif stage == 'simulation':
                if not sim.result or sim.paint_future or sim.fade_to is not None or sim.painted_key != sim.paint_key() or app.tiles.pending or app.dirty or app.render_future:
                    app.after(60, check)
                    return
                assert sim.flow.trails
                assert not sim.running
                for target, method in ((app.canvas, 'coords'), (sim.slider, 'set'), (sim.time_label, 'configure')):
                    spy = patch.object(target, method, wraps=getattr(target, method))
                    spies.append((spy, spy.start()))
                paused_at = time.monotonic()
                stage = 'paused'
            elif stage == 'paused':
                if time.monotonic() - paused_at < .7:
                    app.after(60, check)
                    return
                assert all(mock.call_count == 0 for _, mock in spies), [mock.call_count for _, mock in spies]
                for spy, _ in spies:
                    spy.stop()
                spies.clear()
                before = {item: app.canvas.coords(item) for item in sim.flow.items}
                sim.toggle_play()
                app.after(150, lambda: finish_motion(before))
                return
            app.after(60, check)
        except Exception as error:
            import traceback
            traceback.print_exc()
            failures.append(error)
            for spy, _ in spies:
                spy.stop()
            app.close()

    def finish_motion(before):
        try:
            assert any(app.canvas.coords(item) != coords for item, coords in before.items())
            app.simulation.toggle_play()
            http.assert_not_called()
            app.show_map_options()
            app.map_options.choose(True)
            assert app.tiles.offline and not app.tiles.local_path
            print('GUI performance smoke passed: offline cache, raster pack, attribution, '
                  'source failure recovery, parent-tile zoom, saved settings, zero paused '
                  'canvas/slider/label updates, smooth resume, no HTTP.', flush=True)
        except Exception as error:
            failures.append(error)
            import traceback
            traceback.print_exc()
        finally:
            app.close()

    app.after(100, check)
    app.mainloop()
    if app.tiles:
        app.tiles.pool.shutdown(wait=True, cancel_futures=True)
    if failures:
        raise SystemExit(1)
