"""Exercise a real CustomTkinter window and asynchronous traffic controls."""
import sys
from pathlib import Path
import time
from dataclasses import replace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import ImageGrab
from citycollapse.app import CityCollapseApp

app = CityCollapseApp()
errors, stages = [], []
started = time.monotonic()
first_trail = None


def callback_error(kind, error, traceback):
    errors.append(error)
    print('GUI callback error:', repr(error), flush=True)
    app.close()


app.report_callback_exception = callback_error


def ready():
    return app.traffic_result and app.result_key == app.requested_key and not app.traffic_future


def check():
    global first_trail
    try:
        if time.monotonic() - started > 90:
            raise AssertionError(f'GUI timed out at {stages}')
        if not app.datasets or not app.map_image or not ready():
            app.after(100, check)
            return
        if not stages:
            if not app.traffic_image:
                app.after(100, check)
                return
            assert app.mode == 'Traffic simulation'
            assert app.font_name == 'VT323'
            assert len(app.traffic_result.links) == 4448
            assert app.flow_layer.trails
            first_trail = next(item for item in app.flow_layer.items if app.canvas.itemcget(item, 'state') == 'normal')
            stages.append(tuple(app.canvas.coords(first_trail)))
            app.set_playback_speed('3600x')
            app.toggle_simulation()
            stages.append('playing')
            app.after(650, check)
            return
        stage = stages[-1]
        if stage == 'playing':
            assert app.clock_s > 200
            assert tuple(app.canvas.coords(first_trail)) != stages[0], 'Flow trail did not move'
            app.toggle_simulation()
            image_before_seek = app.canvas.itemcget(app.traffic_item, 'image')
            app.seek_hour(8)
            assert app.canvas.itemcget(app.traffic_item, 'image') == image_before_seek, 'Seeking cleared the traffic image'
            stages.append('hour')
        elif stage == 'hour':
            assert app.traffic_result.hour == 8 and not app.running
            app.hospitals_var.set(False)
            app.fire_var.set(False)
            road = app.datasets['views']['KML road graph']['roads'][0]
            point = road.paths[0][len(road.paths[0]) // 2]
            app.camera = replace(app.camera, x=point[0], y=point[1], zoom=16)
            app.show_all()
            app.pick(app.camera.width / 2, app.camera.height / 2)
            assert app.action_target and app.action_target[0] == 'edge', app.action_target
            app.toggle_block_target()
            assert app.action_target[1] in app.flow_layer.blocked
            assert app.canvas.itemcget(app.traffic_item, 'image'), 'Blocking cleared the traffic image'
            stages.append('road blocked')
        elif stage == 'road blocked':
            identifier = next(iter(app.blocked_edges))
            assert app.traffic_result.links[identifier].closed
            assert app.traffic_result.links[identifier].flow == 0
            r = app.traffic_result
            assert abs(r.affected_demand - r.rerouted_demand - r.unmet_demand) < 1e-6
            assert app.block_button.cget('text') == 'Unblock road'
            app.toggle_block_target()
            stages.append('road restored')
        elif stage == 'road restored':
            assert not any(s.closed for s in app.traffic_result.links.values())
            node = next(n for n in app.datasets['views']['KML road graph']['nodes'] if n['degree'] >= 3)
            app.camera = replace(app.camera, x=node['point'][0], y=node['point'][1], zoom=16)
            app.show_all()
            app.pick(app.camera.width / 2, app.camera.height / 2)
            assert app.action_target == ('node', node['id'])
            app.toggle_block_target()
            stages.append('junction blocked')
        elif stage == 'junction blocked':
            node = next(iter(app.blocked_nodes))
            incident_ids = [e['id'] for e in app.traffic_model.edges if node in (e['source'], e['target'])]
            assert incident_ids and all(app.traffic_result.links[e].closed and app.traffic_result.links[e].flow == 0 for e in incident_ids)
            app.clear_blocks()
            stages.append('clear')
        elif stage == 'clear':
            assert not app.blocked_edges and not app.blocked_nodes
            assert not any(s.closed for s in app.traffic_result.links.values())
            app.set_mode('KML width shading')
            app.set_width_field('RR_width_B')
            app.set_mode('OSM road graph')
            app.set_mode('Traffic simulation')
            app.hospitals_var.set(True)
            hospital = app.datasets['hospitals'][0]
            app.camera = replace(app.camera, x=hospital['point'][0], y=hospital['point'][1])
            app.pick(app.camera.width / 2, app.camera.height / 2)
            assert app.detail_title.cget('text') == hospital['Name']
            app.show_all()
            app.fire_var.set(True)
            station = app.datasets['fire'][0]
            app.camera = replace(app.camera, x=station['point'][0], y=station['point'][1])
            app.pick(app.camera.width / 2, app.camera.height / 2)
            assert app.detail_title.cget('text') == station['FIRE_STAName']
            app.show_all()
            app.reset_camera()
            app.set_playback_speed('60x')
            app.flow_var.set(False)
            app.refresh_traffic_layer()
            app.pinned = True
            stages.append('capture')
            app.after(3000, check)
            return
        else:
            assert app.traffic_image
            folder = Path('.tmp')
            folder.mkdir(exist_ok=True)
            ImageGrab.grab(bbox=(app.winfo_rootx(), app.winfo_rooty(),
                                app.winfo_rootx() + app.winfo_width(),
                                app.winfo_rooty() + app.winfo_height())).save(folder / 'traffic-smoke.png')
            print(f'GUI smoke passed: hourly playback, real edge/node picking, blocking, unblocking, clear, map modes and facilities; {len(app.tiles.images)} basemap tiles.', flush=True)
            app.close()
            return
        app.after(150, check)
    except Exception as error:
        import traceback
        traceback.print_exc()
        errors.append(error)
        app.close()


app.after(250, check)
app.mainloop()
if errors:
    raise SystemExit(1)
