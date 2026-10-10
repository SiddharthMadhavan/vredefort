"""Five-agent Tk flow with explicitly synthetic local HTTP/CSV test fixtures."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vredefort.app import VredefortApp
from vredefort.geometry import project
from vredefort.historical_traffic import HistoricalDataset
from vredefort.live_traffic import sample_road
from vredefort.traffic_agents import TrafficAnalysts
from vredefort.agent_catalog import AGENTS
from agent_fixture import fixture_server
from history_fixture import write_history


with tempfile.TemporaryDirectory() as temporary, fixture_server(chat_delay=.3) as (url, requests), \
        patch('vredefort.live_traffic.FLOW_URL', url + '/flow'):
    folder = Path(temporary)
    app = VredefortApp()
    started = time.monotonic()
    failures = []
    stage = 'startup'
    road_id = None

    def factory(config):
        agents = TrafficAnalysts({**config, 'tomtom_key': 'fixture-key', 'ollama_url': url,
                                 'history_csv': str(folder / 'history.csv')})
        agents.historical.dataset = HistoricalDataset(folder / 'history.csv', folder / 'cache')
        return agents

    app.agent_factory = factory

    def check():
        global stage, road_id
        try:
            assert time.monotonic() - started < 45, (
                f'Timed out at {stage}; window={app.winfo_width()}, '
                f'panel={app.analyst_panel.winfo_width()}, scale={app._get_window_scaling()}')
            panel = app.analyst_panel
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
                road = min(candidates, key=lambda pair: pair[0])[1]
                road_id = road.id
                point = project(*sample_road(road)[0])
                app.camera = replace(app.camera, x=point[0], y=point[1], zoom=15)
                edges = {edge for node in (road.properties['source'], road.properties['target'])
                         for edge in app.network.edge_ids[node]}
                write_history(folder / 'history.csv', sorted(edges))
                app.select_road(road_id)
                app.canvas.focus_set()
                app.canvas.event_generate('<Return>')
                assert app.agent_busy
                stage = 'historical_stream'
            elif stage == 'historical_stream':
                if not panel.history_reply.source:
                    app.after(30, check)
                    return
                assert app.agent_busy, 'Pipeline stopped being busy between the two agents'
                assert 'Test fixture analyst' in panel.reply.source
                panel.select_agent('02 History')
                assert panel.active_agent == 'historical'
                assert 'HISTORICAL BASELINE' in panel.target.cget('text')
                before = app.camera.x
                app.pan_keyboard(100, 0)
                assert app.camera.x > before, 'Map froze while agent 2 streamed'
                stage = 'complete'
            elif stage == 'complete':
                if app.agent_busy or app.agent_thread.is_alive():
                    app.after(40, check)
                    return
                content = panel.history_reply.get('1.0', 'end')
                assert 'model-generated baseline' in content and '**' not in content and '##' not in content
                assert panel.history_reply.tag_ranges('heading2') and panel.history_reply.tag_ranges('strong')
                evidence = json.loads(panel.evidence.get('1.0', 'end'))
                assert evidence['model_generated'] and evidence['selected_road']['id'] == road_id
                assert evidence['observations'][0]['historical_baseline']['overall']['samples'] == 21
                assert panel.evidences['historical']['synthetic']
                assert 'synthetic' not in panel.evidence.get('1.0', 'end').lower()
                assert len([body for kind, body in requests if kind == 'POST']) == 5
                for spec in AGENTS:
                    panel.select_agent(spec.choice)
                    assert panel.replies[spec.key].source, f'Missing reply for {spec.key}'
                    assert spec.title in panel.heading.cget('text')
                    assert json.loads(panel.evidence.get('1.0', 'end'))['selected_road']['id'] == road_id
                    before = panel.replies[spec.key].get('1.0', 'end')
                    panel.replies[spec.key].insert('end', 'USER EDIT')
                    assert panel.replies[spec.key].get('1.0', 'end') == before
                assert 'Test fixture network analyst' in panel.replies['network'].source
                assert 'Test fixture improvement planner' in panel.replies['planner'].source
                assert 'Test fixture critical reviewer' in panel.replies['review'].source
                assert '5 complete, 0 failed' in panel.pipeline_status.cget('text')
                live_copy, history_copy = panel.reply.source, panel.history_reply.source
                panel.select_agent('01 Live')
                assert panel.reply.source == live_copy and panel.history_reply.source == history_copy
                assert json.loads(panel.evidence.get('1.0', 'end'))['source'] == 'TomTom Flow Segment Data'
                panel.select_agent('05 Review and final recommendations')
                stage = 'capture'
            elif stage == 'capture':
                if os.environ.get('VREDEFORT_SMOKE_SCREENSHOT') and sys.platform == 'win32':
                    from PIL import ImageGrab
                    app.lift()
                    app.update_idletasks()
                    Path('.tmp').mkdir(exist_ok=True)
                    ImageGrab.grab(window=app.winfo_id()).save('.tmp/agents-smoke.png')
                app.geometry('760x520')
                stage = 'compact'
            elif stage == 'compact':
                # Windows can resize the toplevel before Tk places its children.
                # Wait for the requested geometry and panel layout to settle;
                # the overall deadline still detects a persistent layout failure.
                expected_width = round(760 * app._get_window_scaling())
                if abs(app.winfo_width() - expected_width) > 1 or abs(panel.winfo_width() - app.winfo_width() / 2) > 2:
                    app.after(50, check)
                    return
                assert panel.winfo_width() <= app.winfo_width() / 2 + 2
                reply = panel.replies['review']
                if reply.winfo_rooty() + reply.winfo_height() > panel.winfo_rooty() + panel.winfo_height():
                    app.after(50, check)
                    return
                assert reply.winfo_height() >= 60, 'Agent picker/headers squeezed out the reply'
                assert reply.winfo_rooty() + reply.winfo_height() <= panel.winfo_rooty() + panel.winfo_height()
                app.analyze_selected()
                stage = 'cancel_review'
            elif stage == 'cancel_review':
                if not panel.replies['review'].source:
                    app.after(30, check)
                    return
                generation = app.agent_generation
                app.select_node(app.network.roads_by_id[road_id].properties['source'])
                for spec in AGENTS:
                    app.agent_events.put((generation, 'agent_event', {
                        'agent': spec.key, 'kind': 'token', 'value': 'STALE AGENT RESULT'}))
                app.poll_analyst()
                assert not app.agent_busy and app.agent_cancel.is_set()
                assert all('STALE AGENT RESULT' not in reply.source for reply in panel.replies.values())
                app.close_analyst()
                stage = 'closed'
            elif stage == 'closed':
                if app.agent_thread.is_alive():
                    app.after(30, check)
                    return
                assert not panel.place_info() and app.map_area.winfo_width() == app.winfo_width()
                print('Five-agent GUI smoke passed: Enter, sequential streaming, all agent views, '
                      'separate evidence, progress, Markdown, compact layout, responsive map, '
                      'review cancellation, and stale-result protection.')
                app.close()
                return
            app.after(50, check)
        except Exception as error:
            import traceback
            traceback.print_exc()
            failures.append(error)
            app.close()

    def callback_error(kind, error, traceback):
        failures.append(error)
        print('GUI callback failed:', repr(error), flush=True)
        app.close()

    app.report_callback_exception = callback_error
    app.after(150, check)
    app.mainloop()
    if failures:
        raise SystemExit(1)
