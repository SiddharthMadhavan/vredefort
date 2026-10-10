"""Real synthetic replay, closure impacts and five-agent analysis together."""
from dataclasses import replace
from pathlib import Path
import os
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vredefort.app import VredefortApp
from vredefort.agent_catalog import AGENTS
from vredefort.historical_traffic import HistoricalDataset
from vredefort.traffic_agents import TrafficAnalysts
from agent_fixture import fixture_server
from history_fixture import write_history


with tempfile.TemporaryDirectory() as temporary, fixture_server(chat_delay=.25) as (url, requests), \
        patch('vredefort.live_traffic.FLOW_URL', url + '/flow'):
    folder = Path(temporary)
    app = VredefortApp()
    started = time.monotonic()
    stage, failures = 'startup', []
    baseline_result = baseline_bitmap = baseline_key = None
    road_id = 'kml_merged_e_8287_0_22'

    def factory(config):
        agents = TrafficAnalysts({**config, 'tomtom_key': 'fixture-key', 'ollama_url': url,
                                 'history_csv': str(folder / 'history.csv')})
        agents.historical.dataset = HistoricalDataset(folder / 'history.csv', folder / 'cache')
        return agents

    app.agent_factory = factory

    def check():
        global stage, baseline_result, baseline_bitmap, baseline_key
        try:
            assert time.monotonic() - started < 65, f'Timed out at {stage}'
            sim = app.simulation
            assert not sim.error, sim.error
            if not app.network or not app.map_image:
                app.after(50, check)
                return
            if stage == 'startup':
                assert sim.model is None
                assert not sim.heatmap_enabled and sim.heatmap_button.cget('text') == 'Heatmap: OFF'
                app.set_mode('Traffic simulation')
                stage = 'loaded'
            elif stage == 'loaded':
                if not sim.result or sim.bitmap_camera != app.camera:
                    app.after(50, check)
                    return
                assert len(sim.result.links) == 4448
                baseline_result, baseline_bitmap, baseline_key = sim.result, sim.bitmap.tobytes(), sim.requested_key
                sim.heatmap_button.invoke()
                assert sim.heatmap_enabled and sim.heatmap_button.cget('text') == 'Heatmap: ON'
                stage = 'heatmap_on'
            elif stage == 'heatmap_on':
                if sim.painted_key != sim.paint_key() or sim.fade_to is not None:
                    app.after(50, check)
                    return
                assert sim.bitmap.tobytes() != baseline_bitmap, 'Heatmap did not change the display'
                assert sim.result is baseline_result and sim.requested_key == baseline_key
                assert sim.clock_s == 0 and app.selection is None
                # Rapid clicks must leave the last requested view visible.
                for _ in range(3):
                    sim.heatmap_button.invoke()
                stage = 'heatmap_off'
            elif stage == 'heatmap_off':
                if sim.painted_key != sim.paint_key() or sim.fade_to is not None:
                    app.after(50, check)
                    return
                assert not sim.heatmap_enabled and sim.bitmap.tobytes() == baseline_bitmap
                assert sim.result is baseline_result and sim.requested_key == baseline_key
                sim.heatmap_button.invoke()
                app.select_road(road_id)
                sim.seek(8)
                sim.toggle_block()
                stage = 'blocked'
            elif stage == 'blocked':
                if sim.result_key != sim.requested_key or sim.result.hour != 8:
                    app.after(50, check)
                    return
                assert sim.result.links[road_id].closed
                assert sim.report.loaded_roads and sim.report.diversions
                assert road_id in sim.flow.blocked
                assert abs(sim.result.affected_demand - sim.result.rerouted_demand - sim.result.unmet_demand) < 1e-6
                assert all(road_id not in option.route.edge_ids for option in sim.report.diversions)
                sim.show_impacts()
                for tab in ('Roads', 'Facilities', 'Diversions'):
                    sim.impact_panel.set_tab(tab)
                    assert sim.impact_panel.report == sim.report
                sim.preview_route(sim.report.diversions[0])
                sim.impact_window.withdraw()
                road = app.network.roads_by_id[road_id]
                edges = {edge for node in (road.properties['source'], road.properties['target'])
                         for edge in app.network.edge_ids[node]}
                write_history(folder / 'history.csv', sorted(edges))
                sim.toggle_play()
                app.analyze_selected()
                stage = 'agents'
            elif stage == 'agents':
                if app.agent_busy or app.agent_thread.is_alive():
                    app.after(50, check)
                    return
                if sim.running:
                    assert sim.elapsed > .1 and sim.clock_s > 8 * 3600
                    sim.toggle_play()
                # Playback keeps changing the requested frame. Pause after
                # verifying concurrent motion, then inspect a settled frame.
                if sim.painted_key != sim.paint_key() or sim.fade_to is not None:
                    app.after(50, check)
                    return
                assert all(app.analyst_panel.replies[spec.key].source for spec in AGENTS)
                assert len([body for kind, body in requests if kind == 'POST']) == 5
                assert sim.elapsed > .1 and sim.clock_s > 8 * 3600
                assert sim.result.links[road_id].closed
                assert sim.heatmap_enabled, 'Scenario update reset the heatmap toggle'
                app.analyst_panel.select_agent('05 Review and final recommendations')
                stage = 'capture'
                app.after(250, check)
                return
            elif stage == 'capture':
                if os.environ.get('VREDEFORT_SMOKE_SCREENSHOT') and sys.platform == 'win32':
                    from PIL import ImageGrab
                    Path('.tmp').mkdir(exist_ok=True)
                    ImageGrab.grab(window=app.winfo_id()).save('.tmp/simulation-agents-smoke.png')
                stage = 'compact'
                app.geometry('760x520')
            elif stage == 'compact':
                expected = round(760 * app._get_window_scaling())
                if abs(app.winfo_width() - expected) > 1 or abs(app.analyst_panel.winfo_width() - app.winfo_width() / 2) > 2:
                    app.after(50, check)
                    return
                app.update_idletasks()
                if os.environ.get('VREDEFORT_SMOKE_SCREENSHOT') and sys.platform == 'win32':
                    from PIL import ImageGrab
                    Path('.tmp').mkdir(exist_ok=True)
                    ImageGrab.grab(window=app.winfo_id()).save('.tmp/simulation-compact-smoke.png')
                assert app.details.winfo_rooty() + app.details.winfo_height() <= app.winfo_rooty() + app.winfo_height(), (
                    f'Simulation panel overflows: details={app.details.winfo_height()}, '
                    f'window={app.winfo_height()}, controls={sim.frame.winfo_reqheight()}, '
                    f'body={app.detail_body.cget("height")}, scale={app._get_window_scaling()}')
                assert sim.frame.winfo_ismapped() and sim.block_button.winfo_ismapped()
                assert sim.heatmap_button.winfo_ismapped()
                app.close_analyst()
                node_id = app.network.roads_by_id[road_id].properties['source']
                app.select_node(node_id)
                sim.toggle_block()
                stage = 'junction'
            elif stage == 'junction':
                if sim.result_key != sim.requested_key:
                    app.after(50, check)
                    return
                node = app.selection[1]
                assert node in sim.result.blocked_nodes
                assert all(sim.result.links[edge].closed for edge in app.network.edge_ids[node])
                sim.clear_blocks()
                stage = 'cleared'
            elif stage == 'cleared':
                if sim.result_key != sim.requested_key:
                    app.after(50, check)
                    return
                assert not sim.report.affected_roads
                assert not any(state.closed for state in sim.result.links.values())
                sim.seek(9)
                sim.seek(10)
                stage = 'latest_hour'
            elif stage == 'latest_hour':
                if sim.result_key != sim.requested_key:
                    app.after(50, check)
                    return
                assert sim.result.hour == 10, 'Superseded scenario was displayed'
                app.set_mode('Explore + agents')
                assert not sim.enabled and not sim.running and not sim.frame.winfo_ismapped()
                assert app.canvas.itemcget(sim.item, 'state') == 'hidden'
                assert all(reply.source for reply in app.analyst_panel.replies.values()), 'Switching modes erased agent results'
                print('Simulation GUI smoke passed: real replay, road/junction blocks, impacts, diversions, '
                      'conservation, default-off heatmap, reversible/rapid toggles, animation with all five agents, '
                      'compact layout, clear, stale-scenario protection and modes.')
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
