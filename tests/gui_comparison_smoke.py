"""Paired maps with the real local traffic model; one application mainloop."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vredefort.app import VredefortApp

app = VredefortApp()
started = time.monotonic()
stage, failures = 'startup', []
road_id = 'kml_merged_e_19725_0_1'


def ready(view):
    return view.displayed_result_key == app.simulation.requested_key and view.painted_key is not None and view.painted_key[0] == view.camera


def check():
    global stage
    try:
        assert time.monotonic()-started < 100, f'Timed out at {stage}'
        sim = app.simulation
        view = sim.comparison
        assert not sim.error, sim.error
        if stage == 'startup':
            if not app.network or not app.map_image:
                app.after(60, check)
                return
            app.set_mode('Traffic simulation')
            stage = 'loaded'
        elif stage == 'loaded':
            if not sim.baseline_result:
                app.after(60, check)
                return
            sim.compare_button.invoke()
            view = sim.comparison
            road = app.network.roads_by_id[road_id]
            point = road.paths[0][len(road.paths[0])//2]
            view.camera = replace(view.camera, x=point[0], y=point[1], zoom=16)
            stage = 'baseline'
        elif stage == 'baseline':
            if not ready(view):
                app.after(60, check)
                return
            assert len(view.images) == 2
            assert sim.baseline_result is sim.result
            road = app.network.roads_by_id[road_id]
            point = road.paths[0][len(road.paths[0])//2]
            x, y = view.camera.screen(point)
            view.press(SimpleNamespace(widget=view.canvases[1], x=x, y=y))
            view.release(SimpleNamespace(x=x, y=y))
            assert app.selection is not None, 'Comparison map did not select a road or junction'
            # Exact vertices can be junctions; use the road selection for this closure.
            app.select_road(road_id)
            sim.seek(8)
            view.tick(time.perf_counter())
            view.block.invoke()
            stage = 'blocked'
        elif stage == 'blocked':
            if not ready(view):
                app.after(60, check)
                return
            assert sim.result.hour == sim.baseline_result.hour == 8
            assert sim.result.links[road_id].closed and not sim.baseline_result.links[road_id].closed
            assert sim.result.links[road_id].flow == 0 and sim.baseline_result.links[road_id].flow > 0
            assert sim.report.loaded_roads and sim.report.facilities
            assert abs(sim.result.rerouted_demand + sim.result.unmet_demand - sim.result.affected_demand) < 1e-6
            assert str(sim.report.facilities[0].name) in view.facilities.get('1.0', 'end')
            view.fit_impacts()
            view.heatmap.invoke()
            stage = 'capture'
        elif stage == 'capture':
            if not ready(view) or view.painted_key[3] != sim.heatmap_enabled:
                app.after(60, check)
                return
            from PIL import ImageGrab
            Path('.tmp').mkdir(exist_ok=True)
            view.window.lift()
            view.window.update_idletasks()
            assert view.block.winfo_height() >= round(30*view.block._get_widget_scaling())
            ImageGrab.grab(window=view.window.winfo_id()).save('.tmp/comparison-smoke.png')
            # Anchored zoom and drag affect a single camera used by both maps.
            point = view.camera.world(80, 80)
            view.zoom(1, 80, 80)
            assert view.camera.world(80, 80) == point
            old = view.camera
            view.press(SimpleNamespace(widget=view.canvases[0], x=80, y=80))
            view.drag(SimpleNamespace(x=120, y=100))
            view.release(SimpleNamespace(x=120, y=100))
            assert view.camera.x < old.x
            node = app.network.roads_by_id[road_id].properties['source']
            sim.clear_blocks()
            app.select_node(node)
            sim.toggle_block()
            sim.seek(9)
            sim.seek(10)
            stage = 'junction'
        elif stage == 'junction':
            if not ready(view):
                app.after(60, check)
                return
            assert sim.result.hour == sim.baseline_result.hour == 10
            node = app.selection[1]
            assert all(sim.result.links[edge].closed and not sim.baseline_result.links[edge].closed
                       for edge in app.network.edge_ids[node])
            sim.clear_blocks()
            view.reset()
            view.window.geometry('900x650')
            stage = 'cleared'
        elif stage == 'cleared':
            if not ready(view):
                app.after(60, check)
                return
            assert sim.result is sim.baseline_result and not sim.report.affected_roads
            assert all(canvas.winfo_height() >= 100 for canvas in view.canvases)
            assert view.block.winfo_rooty()+view.block.winfo_height() <= view.window.winfo_rooty()+view.window.winfo_height()
            assert view.table.winfo_rooty()+view.table.winfo_height() <= view.window.winfo_rooty()+view.window.winfo_height()
            assert 'synthetic' not in sim.status.cget('text').lower()
            sim.show_model()
            view.window.withdraw()
            sim.show_comparison()
            assert view.window.state() != 'withdrawn'
            app.set_mode('Explore + agents')
            assert view.window.state() == 'withdrawn'
            print('Comparison GUI smoke passed: paired maps, road/junction closures, matched hours, '
                  'facility flags, conservation, heatmap, linked pan/zoom, latest request, compact layout, clear and reopen.')
            app.close()
            return
        app.after(60, check)
    except Exception as error:
        import traceback
        traceback.print_exc()
        failures.append(error)
        app.close()


def callback_error(kind, error, tb):
    failures.append(error)
    print('GUI callback failed:', repr(error), flush=True)
    app.close()


app.report_callback_exception = callback_error
app.after(150, check)
app.mainloop()
if failures:
    raise SystemExit(1)
