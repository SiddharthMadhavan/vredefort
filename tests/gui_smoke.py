"""Open the real GUI, exercise it, capture it and close. No second event loop."""
import sys
from pathlib import Path
import time
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import ImageGrab
from citycollapse.app import CityCollapseApp

app = CityCollapseApp()
errors, stages = [], []
started = time.monotonic()

def callback_error(kind, error, traceback):
    errors.append(error)
    print('GUI callback error:', repr(error), flush=True)
    app.close()

app.report_callback_exception = callback_error

def check():
    try:
        if time.monotonic() - started > 60:
            raise AssertionError('GUI startup timed out')
        if not app.datasets or not app.map_image:
            app.after(250, check)
            return
        if not stages:
            assert app.simulation and len(app.simulation.vehicles) == 5
            assert app.font_name == 'VT323'
            app.count_entry.delete(0, 'end'); app.count_entry.insert(0, '30')
            app.speed_entry.delete(0, 'end'); app.speed_entry.insert(0, '15')
            app.initialize_cars()
            assert len(app.simulation.vehicles) == 30
            app.toggle_simulation()
            stages.append('running')
            app.after(600, check)
        elif stages[-1] == 'running':
            assert app.simulation.elapsed_s > .2
            app.toggle_simulation()
            app.set_mode('KML road graph')
            app.hospitals_var.set(False); app.fire_var.set(False); app.invalidate()
            node = app.datasets['views']['KML road graph']['nodes'][10]
            from dataclasses import replace
            app.camera = replace(app.camera, x=node['point'][0], y=node['point'][1], zoom=15)
            app.invalidate()
            stages.append('node')
            app.after(700, check)
        elif stages[-1] == 'node':
            x, y = app.camera.width / 2, app.camera.height / 2
            node = app.node_at(x, y)
            assert node is not None
            app.pick(x, y)
            assert app.pinned
            app.show_all()
            app.set_mode('OSM road graph')
            assert app.mode == 'OSM road graph'
            app.set_mode('KML width shading')
            app.set_width_field('RR_width_B')
            app.set_width_field('RR_WIDTH_P')
            app.hospitals_var.set(True); app.fire_var.set(True)
            app.reset_camera()
            stages.append('capture')
            app.after(6000, check)
        else:
            assert app.map_image is not None
            folder = Path('.tmp'); folder.mkdir(exist_ok=True)
            ImageGrab.grab(bbox=(app.winfo_rootx(), app.winfo_rooty(), app.winfo_rootx() + app.winfo_width(), app.winfo_rooty() + app.winfo_height())).save(folder / 'desktop-smoke.png')
            print(f'GUI smoke passed: real Tk window, {len(app.tiles.images)} loaded map tiles, dataset switches, hover/pin, 30 moving cars and clean shutdown.', flush=True)
            app.close()
    except Exception as error:
        errors.append(error)
        print('GUI smoke failed:', repr(error), flush=True)
        app.close()

app.after(250, check)
app.mainloop()
if errors:
    raise SystemExit(1)
