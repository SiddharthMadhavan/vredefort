"""Exercise emergency access on the real GUI and datasets, entirely offline."""
from dataclasses import replace
from pathlib import Path
import os
import sys
import tempfile
import time
from unittest.mock import patch
from PIL import ImageGrab

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from citycollapse.app import CityCollapseApp
from citycollapse.emergency_rendering import visible_risks, route_paths


with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
        'CITYCOLLAPSE_USER_DIR': temporary, 'CITYCOLLAPSE_MAP_OFFLINE': 'true', 'CITYCOLLAPSE_MAP_PATH': ''}):
    app = CityCollapseApp()
    started, stage, failures = time.monotonic(), 'startup', []
    baseline_pixels = report = blocked_node = None

    def settled(sim):
        return sim.result_key == sim.requested_key and sim.painted_key == sim.paint_key() and sim.fade_to is None

    def check():
        global stage, baseline_pixels, report, blocked_node
        try:
            assert time.monotonic() - started < 70, 'Timed out at ' + stage
            sim, emergency = app.simulation, app.simulation.emergency
            assert not sim.error and not emergency.error, (sim.error, emergency.error)
            if stage == 'startup':
                if not app.network or not app.map_image:
                    app.after(60, check)
                    return
                assert app.title() == 'vredefort / Road explorer'
                assert not emergency.enabled and emergency.report is None
                app.set_mode('Traffic simulation')
                stage = 'simulation'
            elif stage == 'simulation':
                if not sim.result or not settled(sim):
                    app.after(60, check)
                    return
                assert sim.emergency_button.cget('state') == 'normal'
                baseline_pixels = sim.bitmap.tobytes()
                sim.emergency_button.invoke()
                stage = 'emergency'
            elif stage == 'emergency':
                if not emergency.current_report or not settled(sim):
                    app.after(60, check)
                    return
                report = emergency.report
                assert len(report.points) == 6618
                assert len(report.anchors) + len(report.skipped) == len(sim.datasets['hospitals']) + len(sim.datasets['fire'])
                assert len([p for p in report.locations if p.kind == 'hospitals']) == 255
                assert not report.skipped and len(report.anchors) == 276
                assert emergency.window.title() == 'vredefort / Emergency services'
                assert emergency.panel.report is report and emergency.panel.rows
                assert sim.bitmap.tobytes() != baseline_pixels
                assert not sim.running and sim.clock_s == 0
                emergency.window.withdraw()
                Path('.tmp').mkdir(exist_ok=True)
                ImageGrab.grab(window=app.winfo_id()).save('.tmp/emergency-map-smoke.png')
                emergency.panel.kind.set('Fire stations')
                emergency.panel.change_kind('Fire stations')
                assert emergency.kind == 'fire'
                emergency.panel.turn(1)
                assert emergency.panel.page == 1
                emergency.panel.overlay.deselect()
                emergency.panel.toggle_overlay()
                assert not emergency.enabled and emergency.current_report is None
                stage = 'overlay_off'
            elif stage == 'overlay_off':
                if not settled(sim):
                    app.after(60, check)
                    return
                assert sim.bitmap.tobytes() == baseline_pixels
                sim.emergency_button.invoke()
                stage = 'click'
            elif stage == 'click':
                if not emergency.current_report or not settled(sim):
                    app.after(60, check)
                    return
                markers = visible_risks(app.camera, emergency.current_report, 'fire')
                x, y, point = next(m for m in markers if m[2].facility is not None)
                app.pick(x, y)
                assert app.selection == ('node', point.node_id)
                assert emergency.current_route and emergency.current_route.facility == point.facility
                blocked_node = point.node_id
                stage = 'route'
            elif stage == 'route':
                if not settled(sim) or app.display_camera != app.camera:
                    app.after(60, check)
                    return
                route = emergency.current_route
                paths = route_paths(app.network, route)
                points = [route.facility.entrance_point, route.point, *(p for path in paths for p in path)]
                assert all(app.details.winfo_width() + 20 <= app.camera.screen(p)[0] <= app.camera.width - 20
                           and 20 <= app.camera.screen(p)[1] <= app.camera.height - 20 for p in points)
                assert app.canvas.itemcget(sim.item, 'state') == 'normal'
                assert sum(r == 99 and g == 239 and b == 255 for r, g, b, a in sim.bitmap.getdata()) > 100, sim.status.cget('text')
                stage = 'route_capture'
                app.after(400, check)
                return
            elif stage == 'route_capture':
                ImageGrab.grab(window=app.winfo_id()).save('.tmp/emergency-route-smoke.png')
                selected = next(p for p in emergency.report.points if (p.kind, p.node_id) == emergency.selected_target)
                app.clear_selection()
                assert emergency.current_route is None and emergency.selected_target is None
                emergency.focus(selected)
                sim.toggle_block()
                assert emergency.current_report is None and emergency.panel.report is None
                assert not emergency.panel.rows, 'Stale report rows retained after closure'
                stage = 'closure'
            elif stage == 'closure':
                if not emergency.current_report or not settled(sim):
                    app.after(60, check)
                    return
                point = next(p for p in emergency.report.points if p.kind == 'fire' and p.node_id == blocked_node)
                assert point.status == 'lost'
                assert emergency.current_route is None, 'Blocked junction retained an old route'
                assert emergency.report is not report
                emergency.focus(point)
                sim.seek(10)
                sim.seek(11)
                sim.clear_blocks()
                assert emergency.current_report is None
                stage = 'latest'
            elif stage == 'latest':
                if not emergency.current_report or not settled(sim):
                    app.after(60, check)
                    return
                assert emergency.report.hour == 11 and not sim.result.blocked_nodes
                assert not any(p.status == 'lost' for p in emergency.report.points)
                sim.toggle_play()
                stage = 'playback'
                app.after(700, check)
                return
            elif stage == 'playback':
                assert sim.running and sim.elapsed > .2
                sim.toggle_play()
                emergency.panel.kind.set('Healthcare access')
                emergency.panel.change_kind('Healthcare access')
                assert emergency.kind == 'hospitals'
                point = next(p for p in emergency.report.risks('hospitals') if p.facility)
                emergency.focus(point)
                assert emergency.current_route.facility.kind == 'hospitals'
                sim.seek(12)
                assert emergency.current_route is None
                stage = 'hospital_route'
            elif stage == 'hospital_route':
                if not emergency.current_route or not settled(sim):
                    app.after(60, check)
                    return
                assert emergency.report.hour == 12
                point = next(p for p in emergency.report.points if (p.kind, p.node_id) == emergency.selected_target)
                assert emergency.current_route.seconds == point.seconds
                assert emergency.current_route.facility == point.facility
                assert emergency.current_route.facility.facility_type in ('Urban primary health centre', 'Namma Clinic', 'Referral hospital')
                emergency.window.deiconify()
                emergency.window.lift()
                stage = 'capture'
                app.after(400, check)
                return
            elif stage == 'capture':
                emergency.window.update_idletasks()
                assert emergency.panel.assumptions.winfo_rooty() + emergency.panel.assumptions.winfo_height() <= emergency.window.winfo_rooty() + emergency.window.winfo_height()
                assert emergency.panel.assumptions.winfo_height() >= 90 * emergency.panel._get_widget_scaling()
                ImageGrab.grab(window=emergency.window.winfo_id()).save('.tmp/emergency-panel-smoke.png')
                emergency.window.withdraw()
                location = next(p for p in emergency.report.locations if p.kind == 'hospitals' and p.category == 'clinics')
                emergency.focus_location(location)
                assert app.detail_title.cget('text') == location.name
                assert app.selection is None and emergency.current_route is None
                anchor = next(a for a in emergency.report.anchors if a.kind == 'hospitals' and a.distance_m > 250)
                location = next(p for p in emergency.report.locations if (p.kind, p.index) == (anchor.kind, anchor.index))
                sim.focus_points([location.map_point])
                assert emergency.pick(*app.camera.screen(location.map_point))
                assert app.detail_title.cget('text') == location.name
                assert location.map_point == anchor.entrance_point and location.point != location.map_point
                app.geometry('760x520')
                stage = 'compact'
                app.after(400, check)
                return
            elif stage == 'compact':
                app.update_idletasks()
                assert sim.emergency_button.winfo_ismapped()
                assert app.details.winfo_rooty() + app.details.winfo_height() <= app.winfo_rooty() + app.winfo_height(), (
                    app.details.winfo_height(), app.winfo_height(), sim.frame.winfo_reqheight())
                app.set_mode('Explore + agents')
                assert not emergency.window.winfo_viewable()
                assert emergency.current_report is None
                app.set_mode('Traffic simulation')
                stage = 'resume'
            elif stage == 'resume':
                if not emergency.current_report or not settled(sim):
                    app.after(60, check)
                    return
                print('Emergency GUI passed: title, default-off, actual facilities/junctions, overlays, filters, '
                      'pagination, full hospital/station routes, auto-fit, route clearing/updates, closure and baseline, '
                      'rapid seeking, playback, compact layout and modes.', flush=True)
                app.close()
                return
            app.after(60, check)
        except Exception as error:
            import traceback
            traceback.print_exc()
            failures.append(error)
            app.close()

    def callback_error(kind, error, trace):
        failures.append(error)
        print('GUI callback failed:', repr(error), flush=True)
        app.close()

    app.report_callback_exception = callback_error
    app.after(100, check)
    app.mainloop()
    if failures:
        raise SystemExit(1)
