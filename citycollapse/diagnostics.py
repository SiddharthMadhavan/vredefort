"""Offline desktop self-test used to verify release executables."""
from dataclasses import replace
import json
import sys
import time

from PIL import ImageGrab

from .app import CityCollapseApp
from .config import analyst_settings, settings
from .paths import ROOT, USER_DIR, CACHE_DIR
from .user_settings import SETTINGS_FILE


def run_self_test(report_path):
    report, stage, started = {}, 'startup', time.monotonic()
    app = CityCollapseApp()

    def finish(error=None):
        report['status'] = 'failed' if error else 'passed'
        if error:
            report['error'] = type(error).__name__ + ': ' + str(error)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        app.close()

    def check():
        nonlocal stage
        try:
            if time.monotonic() - started > 70:
                raise TimeoutError('Timed out at ' + stage)
            if stage == 'startup':
                if not app.network or not app.map_image:
                    app.after(60, check)
                    return
                assert app.tiles.offline
                assert (ROOT / 'assets/fonts/VT323-Regular.ttf').exists()
                assert (ROOT / 'data/synthetic/bengaluru_road_traffic_synthetic_hourly.csv.gz').exists()
                report.update(roads=len(app.network.roads), nodes=len(app.network.nodes),
                    frozen=bool(getattr(sys, 'frozen', False)), bundled_resources=True)
                assert app.title() == 'vredefort / Road explorer'
                report['app_title'] = app.title()
                if report['frozen']:
                    assert not (ROOT / '.env').exists() and not (ROOT / '.env.local').exists()
                    assert USER_DIR in CACHE_DIR.parents and ROOT not in CACHE_DIR.parents
                    report.update(bundled_env_absent=True, persistent_cache=True)
                app.settings_button.invoke()
                stage = 'settings'
                app.after(450, check)
                return
            elif stage == 'settings':
                panel = app.settings_panel
                values = {'TOMTOM_API_KEY': 'fixture-tomtom-key', 'VITE_CARTO_API_KEY': 'fixture-carto-key',
                    'OLLAMA_BASE_URL': 'http://127.0.0.1:11434', 'OLLAMA_MODEL': 'llama3.1:8b'}
                for key, value in values.items():
                    panel.entries[key].delete(0, 'end')
                    panel.entries[key].insert(0, value)
                assert panel.entries['TOMTOM_API_KEY'].cget('show') == '*'
                panel.save_button.invoke()
                assert analyst_settings()['tomtom_key'] == values['TOMTOM_API_KEY']
                assert 'key=fixture-carto-key' in settings()['tile_url']
                saved = SETTINGS_FILE.read_bytes()
                assert b'fixture-tomtom-key' not in saved and b'fixture-carto-key' not in saved
                report['encrypted_settings_roundtrip'] = True
                panel.entries['OLLAMA_BASE_URL'].delete(0, 'end')
                panel.entries['OLLAMA_BASE_URL'].insert(0, 'invalid')
                panel.save_button.invoke()
                assert SETTINGS_FILE.read_bytes() == saved
                assert 'HTTP' in panel.message.cget('text')
                report['invalid_settings_preserve_profile'] = True
                panel.show()
                assert panel.entries['TOMTOM_API_KEY'].get() == values['TOMTOM_API_KEY']
                panel.window.update_idletasks()
                ImageGrab.grab(window=panel.window.winfo_id()).save(report_path.with_suffix('.settings.png'))
                for key in ('TOMTOM_API_KEY', 'VITE_CARTO_API_KEY'):
                    panel.entries[key].delete(0, 'end')
                panel.save_button.invoke()
                assert analyst_settings()['tomtom_key'] == ''
                assert 'key=fixture-carto-key' not in settings()['tile_url']
                report['key_removal'] = True
                panel.window.withdraw()
                road = app.network.roads_by_id['kml_merged_e_19725_0_1']
                point = road.paths[0][len(road.paths[0]) // 2]
                app.camera = replace(app.camera, x=point[0], y=point[1], zoom=15)
                app.select_road(road.id)
                app.set_mode('Traffic simulation')
                stage = 'simulation'
            elif stage == 'simulation':
                sim = app.simulation
                assert not sim.error, sim.error
                if not sim.result or sim.paint_future or sim.painted_key != sim.paint_key():
                    app.after(60, check)
                    return
                assert len(sim.result.links) == len(app.network.roads)
                sim.toggle_block()
                stage = 'closure'
            elif stage == 'closure':
                sim = app.simulation
                if sim.result_key != sim.requested_key or sim.paint_future or sim.painted_key != sim.paint_key():
                    app.after(60, check)
                    return
                identifier = app.selection[1]
                assert sim.result.links[identifier].closed
                assert not sim.baseline_result.links[identifier].closed
                report.update(simulation=True, closure_and_baseline=True, settings_button=True)
                sim.emergency_button.invoke()
                stage = 'emergency'
            elif stage == 'emergency':
                sim = app.simulation
                assert not sim.emergency.error, sim.emergency.error
                if not sim.emergency.current_report or sim.painted_key != sim.paint_key():
                    app.after(60, check)
                    return
                emergency = sim.emergency.current_report
                assert len(emergency.points) == len(app.network.nodes) * 2
                assert emergency.anchors and sim.emergency.panel.report is emergency
                report.update(emergency_access=True, emergency_facilities=len(emergency.anchors))
                point = next(p for p in emergency.points if p.kind == 'hospitals' and p.facility and p.status == 'delayed')
                sim.emergency.focus(point)
                stage = 'emergency_route'
            elif stage == 'emergency_route':
                sim = app.simulation
                assert sim.emergency.current_route and sim.emergency.current_route.facility.kind == 'hospitals'
                if sim.painted_key != sim.paint_key() or sim.fade_to is not None:
                    app.after(60, check)
                    return
                assert sum(r == 99 and g == 239 and b == 255 for r, g, b, a in sim.bitmap.getdata()) > 100
                report['emergency_route'] = True
                finish()
                return
            app.after(60, check)
        except Exception as error:
            finish(error)

    app.after(100, check)
    app.mainloop()
    if app.tiles:
        app.tiles.pool.shutdown(wait=True, cancel_futures=True)
    app.worker.shutdown(wait=True, cancel_futures=True)
    app.simulation.pool.shutdown(wait=True, cancel_futures=True)
    app.simulation.paint_pool.shutdown(wait=True, cancel_futures=True)
    app.simulation.emergency.pool.shutdown(wait=True, cancel_futures=True)
    return 0 if report.get('status') == 'passed' else 1
