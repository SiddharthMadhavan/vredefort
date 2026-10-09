"""Real Tk widgets + test-only HTTP servers exercise Enter and streamed replies."""
from dataclasses import replace
from pathlib import Path
import json
import os
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from citycollapse.app import CityCollapseApp
from citycollapse.geometry import project
from citycollapse.live_traffic import LiveTrafficAnalyst, sample_road
from agent_fixture import fixture_server


with fixture_server(chat_delay=.3) as (url, requests), patch('citycollapse.live_traffic.FLOW_URL', url + '/flow'):
    app = CityCollapseApp()
    # These explicitly labelled fixture measurements never enter production code.
    app.agent_factory = lambda config: LiveTrafficAnalyst({
        **config, 'tomtom_key': 'fixture-key', 'ollama_url': url})
    started = time.monotonic()
    stage = 'startup'
    road_id = None
    failures = []

    def callback_error(kind, error, traceback):
        failures.append(error)
        print('GUI callback failed:', repr(error), flush=True)
        app.close()

    app.report_callback_exception = callback_error

    def check():
        global stage, road_id
        try:
            assert time.monotonic() - started < 45, f'Timed out at {stage}'
            if not app.network or not app.map_image:
                app.after(50, check)
                return
            if stage == 'startup':
                centre = project(77.5946, 12.9716)
                candidates = []
                for road in app.network.roads:
                    coordinate, direction = sample_road(road)
                    if abs(direction[0]) > .95:
                        point = project(*coordinate)
                        candidates.append((sum((a - b) ** 2 for a, b in zip(point, centre)), road))
                road = min(candidates, key=lambda item: item[0])[1]
                road_id = road.id
                point = project(*sample_road(road)[0])
                app.camera = replace(app.camera, x=point[0], y=point[1], zoom=15)
                app.select_node(road.properties['source'])
                app.analyze_selected()
                assert not app.analyst_panel.place_info(), 'Node Enter incorrectly analyzed a road'
                app.select_road(road_id)
                app.canvas.focus_set()
                app.canvas.event_generate('<Return>')
                assert app.agent_busy, 'Enter binding did not start the analyst'
                assert app.analyst_panel.place_info()
                stage = 'streaming'
            elif stage == 'streaming':
                content = app.analyst_panel.reply.get('1.0', 'end')
                if not content.strip():
                    app.after(30, check)
                    return
                assert app.agent_busy, 'Expected an incremental reply while still generating'
                assert 'Test fixture analyst' in content
                assert abs(app.map_area.winfo_width() - app.winfo_width() / 2) <= 2
                assert abs(app.analyst_panel.winfo_width() - app.winfo_width() / 2) <= 2
                camera = app.camera
                app.pan_keyboard(100, 0)
                assert app.camera.x > camera.x, 'Map froze during analysis'
                assert app.selection == ('road', road_id)
                stage = 'complete'
            elif stage == 'complete':
                if app.agent_busy or app.agent_thread.is_alive():
                    app.after(50, check)
                    return
                reply = app.analyst_panel.reply.get('1.0', 'end')
                assert 'current speed is 24 km/h' in reply
                assert 'observation age is unknown' in reply
                evidence = json.loads(app.analyst_panel.evidence.get('1.0', 'end'))
                assert evidence['selected_road']['id'] == road_id
                assert evidence['available_samples'] >= 1
                assert app.attribution.winfo_width() <= app.map_area.winfo_width()
                assert app.attribution.winfo_x() >= 0
                assert 'fixture-key' not in json.dumps(evidence)
                app.analyst_panel.reply.insert('end', 'USER EDIT')
                assert app.analyst_panel.reply.get('1.0', 'end') == reply, 'Reply should be read-only'
                if os.environ.get('CITYCOLLAPSE_SMOKE_SCREENSHOT'):
                    app.lift()
                    stage = 'capture'
                    app.after(250, check)
                    return
                stage = 'capture'
            elif stage == 'capture':
                if os.environ.get('CITYCOLLAPSE_SMOKE_SCREENSHOT') and sys.platform == 'win32':
                    from PIL import ImageGrab
                    Path('.tmp').mkdir(exist_ok=True)
                    ImageGrab.grab(window=app.winfo_id()).save('.tmp/analyst-smoke.png')
                # A new selection invalidates a running request and queued text.
                app.analyze_selected()
                generation = app.agent_generation
                node_id = app.network.roads_by_id[road_id].properties['source']
                app.select_node(node_id)
                app.agent_events.put((generation, 'token', 'STALE RESULT'))
                app.poll_analyst()
                assert 'STALE RESULT' not in app.analyst_panel.reply.get('1.0', 'end')
                assert not app.agent_busy and app.agent_cancel.is_set()
                app.close_analyst()
                stage = 'closed'
            elif stage == 'closed':
                assert not app.analyst_panel.place_info()
                assert app.map_area.winfo_width() == app.winfo_width()
                assert app.selection and app.selection[0] == 'node'
                print('Agent GUI smoke passed: Enter, right-half panel, streamed reply, evidence, '
                      'responsive map, cancellation, stale-result protection, and close/restore.', flush=True)
                app.close()
                return
            app.after(50, check)
        except Exception as error:
            import traceback
            traceback.print_exc()
            failures.append(error)
            app.close()

    app.after(150, check)
    app.mainloop()
    if failures:
        raise SystemExit(1)
