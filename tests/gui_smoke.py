"""Exercise the real map-only CustomTkinter window and its canvas bindings."""
from dataclasses import replace
from pathlib import Path
import os
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from citycollapse.app import CityCollapseApp, CENTRE
from citycollapse.explore_map import nearest_node, nearest_road

app = CityCollapseApp()
errors = []
started = time.monotonic()
stage = 'startup'
expected_road = None
expected_node = None
saved_selection = None


def callback_error(kind, error, traceback):
    errors.append(error)
    print('GUI callback error:', repr(error), flush=True)
    app.close()


app.report_callback_exception = callback_error


def settled():
    return app.map_image and app.display_camera == app.camera and not app.dirty and not app.render_future


def click(x, y):
    app.canvas.event_generate('<ButtonPress-1>', x=round(x), y=round(y))
    app.canvas.event_generate('<ButtonRelease-1>', x=round(x), y=round(y))


def texts():
    return '\n'.join(str(w.cget('text')) for w in app.detail_body.winfo_children())


def check():
    global stage, expected_road, expected_node, saved_selection
    try:
        assert time.monotonic() - started < 60, f'Timed out at {stage}'
        assert not app.dataset_error, app.dataset_error
        assert not app.render_error, app.render_error
        if not app.network or not settled():
            app.after(100, check)
            return
        if stage == 'startup' and app.tiles and not app.tiles.images:
            app.after(100, check)
            return
        if stage in ('capture', 'capture ready'):
            keys = app.camera.tile_keys()
            assert not any(key in app.tiles.failed for key in keys), 'Basemap tile download failed'
            if any(key not in app.tiles.images for key in keys):
                app.after(100, check)
                return
        if stage == 'startup':
            assert app.camera.zoom == 11
            assert len(app.network.roads) == 4448
            assert len(app.network.nodes) == 3309
            assert 'citycollapse.traffic' not in sys.modules
            assert 'citycollapse.simulation' not in sys.modules
            assert app.tiles and app.tiles.images, 'No real basemap tiles loaded'
            # Pick a central road segment sufficiently far from node hit targets.
            road = app.network.roads_by_id['kml_merged_e_19725_0_1']
            found = False
            for a, b in zip(road.paths[0], road.paths[0][1:]):
                point = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                camera = replace(app.camera, x=point[0], y=point[1], zoom=16)
                x, y = camera.width / 2, camera.height / 2
                if not nearest_node(app.network, camera, x, y):
                    candidate = nearest_road(app.network, camera, x, y)
                    if candidate and candidate.id == road.id:
                        app.camera = camera
                        found = True
                        break
            assert found, 'No suitable road click target'
            app.invalidate()
            stage = 'road'
        elif stage == 'road':
            x, y = app.camera.width / 2, app.camera.height / 2
            click(x, y)
            expected_road = 'kml_merged_e_19725_0_1'
            assert app.selection == ('road', expected_road), app.selection
            assert expected_road in texts() and 'Length' in texts()
            inset = round(16 * app.details._get_widget_scaling())
            assert int(app.details.place_info()['x']) == inset
            assert int(app.details.place_info()['y']) == inset
            expected_node = app.network.roads_by_id[expected_road].properties['source']
            # Exercise the endpoint shortcut in the left panel.
            button = next(w for w in app.detail_body.winfo_children()
                          if str(w.cget('text')).startswith('Inspect node'))
            button.invoke()
            assert app.selection == ('node', expected_node)
            assert expected_node in texts() and 'Connected edges' in texts()
            node = app.network.nodes_by_id[expected_node]
            app.camera = replace(app.camera, x=node['point'][0], y=node['point'][1], zoom=16)
            app.invalidate()
            stage = 'node'
        elif stage == 'node':
            app.clear_selection()
            x, y = app.camera.width / 2, app.camera.height / 2
            app.canvas.event_generate('<Motion>', x=round(x), y=round(y))
            assert app.canvas.coords(app.hover_item)[0] >= 0
            click(x, y)
            assert app.selection == ('node', expected_node), app.selection
            assert 'Longitude / latitude' in texts()
            for edge_id in app.network.edge_ids[expected_node]:
                assert edge_id in texts()
            saved_selection = app.selection
            old = app.camera
            app.canvas.event_generate('<MouseWheel>', delta=120, x=round(x), y=round(y))
            assert app.camera.zoom == old.zoom + 1
            for a, b in zip(old.world(round(x), round(y)), app.camera.world(round(x), round(y))):
                assert abs(a - b) < 1e-12, 'Zoom moved pointer world position'
            assert app.selection == saved_selection
            stage = 'drag'
        elif stage == 'drag':
            old = app.camera
            x, y = old.width // 2, old.height // 2
            app.canvas.event_generate('<ButtonPress-1>', x=x, y=y)
            app.canvas.event_generate('<B1-Motion>', x=x + 80, y=y + 40)
            app.canvas.event_generate('<ButtonRelease-1>', x=x + 80, y=y + 40)
            assert app.selection == saved_selection, 'Dragging selected another feature'
            assert abs(app.camera.x - (old.x - 80 / old.scale)) < 1e-12
            assert abs(app.camera.y - (old.y - 40 / old.scale)) < 1e-12
            old = app.camera
            app.canvas.event_generate('<Right>')
            assert app.camera.x > old.x, 'Keyboard pan failed'
            stage = 'capture'
        elif stage == 'capture':
            if os.environ.get('CITYCOLLAPSE_SMOKE_SCREENSHOT'):
                app.lift()
            stage = 'capture ready'
            app.after(250, check)
            return
        elif stage == 'capture ready':
            if os.environ.get('CITYCOLLAPSE_SMOKE_SCREENSHOT') and sys.platform == 'win32':
                from PIL import ImageGrab
                folder = Path('.tmp')
                folder.mkdir(exist_ok=True)
                ImageGrab.grab(window=app.winfo_id()).save(folder / 'map-explorer.png')
            assert app.details.winfo_y() + app.details.winfo_height() < app.winfo_height() - 30
            # Preview selection can be cleared without disturbing camera position.
            camera = app.camera
            app.clear_button.invoke()
            assert app.selection is None and app.camera == camera
            app.reset_camera()
            assert (app.camera.x, app.camera.y) == CENTRE and app.camera.zoom == 11
            app.geometry('760x520')
            stage = 'small window'
        elif stage == 'small window':
            assert app.details.winfo_y() + app.details.winfo_height() < app.winfo_height() - 30, (
                app.details.winfo_y(), app.details.winfo_height(), app.winfo_height())
            app.camera = replace(app.camera, zoom=18)
            app.zoom(1)
            assert app.camera.zoom == 18
            app.camera = replace(app.camera, zoom=8)
            app.zoom(-1)
            assert app.camera.zoom == 8
            print('GUI smoke passed: real basemap, clickable roads/nodes, left details, '
                  'endpoint shortcuts, hover, anchored zoom, drag/keyboard pan, reset, '
                  'clearing selection and small-window layout.', flush=True)
            app.close()
            return
        app.after(150, check)
    except Exception as error:
        import traceback
        traceback.print_exc()
        errors.append(error)
        print('GUI smoke failed:', repr(error), flush=True)
        app.close()


app.after(100, check)
app.mainloop()
if errors:
    raise SystemExit(1)
