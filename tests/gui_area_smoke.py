"""Junction Enter, connected multi-selection, cancellation, and area simulation."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from citycollapse.analysis_scope import AnalysisScope, connected_roads
from citycollapse.app import CityCollapseApp
from citycollapse.explore_map import nearest_road
from citycollapse.historical_traffic import HistoricalDataset
from citycollapse.live_traffic import road_context, sample_road
from citycollapse.traffic_agents import TrafficAnalysts
from agent_fixture import fixture_server
from history_fixture import write_history


with tempfile.TemporaryDirectory() as temporary, fixture_server(chat_delay=.15) as (url, requests), \
        patch('citycollapse.live_traffic.FLOW_URL', url+'/flow'):
    folder = Path(temporary)
    app = CityCollapseApp()
    started = time.monotonic()
    stage, failures = 'startup', []
    node_id = core = None

    def factory(config):
        pipeline = TrafficAnalysts({**config, 'tomtom_key': 'fixture-key', 'ollama_url': url,
                                    'history_csv': str(folder/'history.csv')})
        pipeline.historical.dataset = HistoricalDataset(folder/'history.csv', folder/'cache')
        return pipeline

    app.agent_factory = factory

    def check():
        global stage, node_id, core
        try:
            assert time.monotonic()-started < 100, f'Timed out at {stage}'
            panel, sim = app.analyst_panel, app.simulation
            if not app.network or not app.map_image:
                app.after(60, check)
                return
            if stage == 'startup':
                road = app.network.roads_by_id['kml_merged_e_19725_0_1']
                node_id = max((road.properties['source'], road.properties['target']), key=lambda node: len(app.network.edge_ids[node]))
                core = tuple(sorted(app.network.edge_ids[node_id]))
                assert len(core) >= 3
                context = road_context(app.network, AnalysisScope.area(core))
                write_history(folder/'history.csv', [item['edge_id'] for item in context['samples']])
                app.select_node(node_id)
                app.canvas.focus_set()
                app.canvas.event_generate('<Return>')
                assert app.agent_busy and isinstance(app.agent_target, AnalysisScope)
                assert 'Junction' in panel.target.cget('text')
                stage = 'junction'
            elif stage == 'junction':
                if app.agent_busy or app.agent_thread.is_alive():
                    app.after(60, check)
                    return
                assert len([kind for kind, _ in requests if kind == 'POST']) == 5
                for evidence in panel.evidences.values():
                    assert evidence['selected_area']['type'] == 'junction'
                    assert evidence['selected_area']['selected_junction_id'] == node_id
                    assert set(evidence['selected_area']['edge_ids']) == set(core)
                app.close_analyst()
                app.select_area(core[:2])
                # Exercise the same Shift-click modifier used on the map.
                added = core[2]
                point = app.network.roads_by_id[added].paths[0][len(app.network.roads_by_id[added].paths[0])//2]
                app.camera = replace(app.camera, x=point[0], y=point[1], zoom=18)
                x, y = app.camera.screen(point)
                picked = nearest_road(app.network, app.camera, x, y)
                assert picked and picked.id not in core[:2]
                app.press(SimpleNamespace(x=x, y=y))
                app.release(SimpleNamespace(x=x, y=y, state=1))
                assert app.selection[0] == 'area' and picked.id in app.selection[1]
                assert connected_roads(app.network, app.selection[1])
                selected = app.selection
                detached = next(road.id for road in app.network.roads if not connected_roads(app.network, [core[0], road.id]))
                app.toggle_area_road(detached)
                assert app.selection == selected
                assert 'connect' in app.selection_notice.cget('text')
                app.analyze_selected()
                stage = 'cancel'
            elif stage == 'cancel':
                if not panel.reply.source:
                    app.after(30, check)
                    return
                generation = app.agent_generation
                app.toggle_area_road(core[0])
                assert app.agent_cancel.is_set() and app.agent_generation > generation
                app.agent_events.put((generation, 'agent_event', {'agent': 'live', 'kind': 'token', 'value': 'STALE AREA RESULT'}))
                app.poll_analyst()
                assert 'STALE AREA RESULT' not in panel.reply.source
                stage = 'restart'
            elif stage == 'restart':
                if app.agent_thread.is_alive():
                    app.after(60, check)
                    return
                app.select_area(core)
                app.analyze_selected()
                stage = 'area'
            elif stage == 'area':
                if app.agent_busy or app.agent_thread.is_alive():
                    app.after(60, check)
                    return
                assert all(reply.source for reply in panel.replies.values())
                for evidence in panel.evidences.values():
                    assert evidence['selected_area']['type'] == 'area'
                    assert set(evidence['selected_area']['edge_ids']) == set(core)
                panel.select_agent('03 Network bottlenecks')
                assert 'Connected area' in panel.target.cget('text')
                app.set_mode('Traffic simulation')
                assert app.selection == ('area', core)
                stage = 'simulation'
            elif stage == 'simulation':
                if not sim.result:
                    app.after(60, check)
                    return
                assert sim.block_button.cget('text') == 'Block area'
                sim.toggle_block()
                stage = 'blocked'
            elif stage == 'blocked':
                if sim.result_key != sim.requested_key:
                    app.after(60, check)
                    return
                assert set(core) <= sim.blocked_edges
                assert all(sim.result.links[edge].closed for edge in core)
                assert sim.block_button.cget('text') == 'Unblock area'
                sim.toggle_block()
                sim.show_comparison()
                stage = 'comparison'
            elif stage == 'comparison':
                view = sim.comparison
                if sim.result_key != sim.requested_key or view.displayed_result_key != sim.requested_key:
                    app.after(60, check)
                    return
                assert sim.result is sim.baseline_result and not sim.blocked_edges
                assert view.selection_label.cget('text').startswith('Connected area')
                view.window.withdraw()
                app.set_mode('Explore + agents')
                app.focus_analyzed_road(AnalysisScope.area(core))
                stage = 'capture'
            elif stage == 'capture':
                if app.display_camera != app.camera:
                    app.after(60, check)
                    return
                assert app.zoom_in_button.cget('state') == ('disabled' if app.camera.zoom == 18 else 'normal')
                points = [point for identifier in core for path in app.network.roads_by_id[identifier].paths for point in path]
                assert all(app.details.winfo_x()+app.details.winfo_width() < app.camera.screen(point)[0] < app.controls.winfo_x() for point in points)
                app.lift()
                app.update_idletasks()
                from PIL import ImageGrab
                Path('.tmp').mkdir(exist_ok=True)
                ImageGrab.grab(window=app.winfo_id()).save('.tmp/area-agents-smoke.png')
                app.clear_selection()
                assert app.selection is None
                print('Area GUI smoke passed: junction Enter, all five area agents, Shift-click, connectivity '
                      'validation, scope cancellation, stale replies, area blocks, comparison and clear.')
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
