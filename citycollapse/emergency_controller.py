"""Cancelable emergency access worker; GUI updates remain on the root loop."""
from concurrent.futures import ThreadPoolExecutor, CancelledError
from threading import Event
import customtkinter as ctk
from .emergency_services import EmergencyAccessModel, SERVICE_NAMES, STATUS_NAMES
from .emergency_panel import EmergencyPanel, minutes
from .presentation import display_text


class EmergencyController:
    def __init__(self, sim):
        self.sim = sim
        self.enabled = False
        self.kind = None
        self.report = self.report_key = self.failed_key = None
        self.window = self.panel = None
        self.future = None
        self.cancel = Event()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='emergency-access')
        self.model = None
        self.error = ''
        self.selected_target = self.route = None

    @property
    def current_report(self):
        return self.report if self.enabled and self.sim.enabled and self.report_key == self.sim.requested_key == self.sim.result_key else None

    @property
    def current_route(self):
        return self.route if self.current_report and self.route and self.sim.app.selection == ('node', self.route.node_id) \
            and self.kind in (None, self.route.facility.kind) else None

    def selection_changed(self):
        if self.selected_target and self.sim.app.selection != ('node', self.selected_target[1]):
            self.selected_target = self.route = None

    def update_button(self):
        self.sim.emergency_button.configure(fg_color='#33533c' if self.enabled else '#15251a')

    def show(self):
        self.enabled = True
        self.failed_key = None
        self.update_button()
        if self.window is None or not self.window.winfo_exists():
            self.window = ctk.CTkToplevel(self.sim.app)
            self.window.title('vredefort / Emergency services')
            scale = self.window._get_window_scaling()
            height = min(800, int((self.window.winfo_screenheight() - 140) / scale))
            self.window.geometry(f'480x{height}+60+40')
            self.window.minsize(460, 520)
            self.window.protocol('WM_DELETE_WINDOW', self.window.withdraw)
            self.panel = EmergencyPanel(self.window, self)
            self.panel.pack(fill='both', expand=True)
        self.panel.overlay.select()
        if self.current_report:
            self.panel.set_report(self.current_report)
        else:
            self.panel.pending('Calculating emergency access...')
        self.window.deiconify()
        self.window.lift()

    def invalidate(self):
        self.cancel.set()
        self.route = None
        self.error = ''
        if self.panel:
            self.panel.pending()

    def suspend(self):
        self.cancel.set()
        if self.window:
            self.window.withdraw()

    def calculate(self, key, baseline, result, cancel):
        if self.model is None:
            self.model = EmergencyAccessModel(self.sim.model, self.sim.datasets, cancel=cancel)
        return key, self.model.analyze(baseline, result, cancel=cancel)

    def tick(self):
        sim = self.sim
        if self.future and self.future.done():
            future, self.future = self.future, None
            try:
                key, report = future.result()
                if self.enabled and sim.enabled and key == sim.requested_key == sim.result_key:
                    self.report_key, self.report = key, report
                    self.error = ''
                    if self.panel:
                        self.panel.set_report(report)
                    if self.selected_target:
                        point = next(p for p in report.points if (p.kind, p.node_id) == self.selected_target)
                        self.focus(point, fit=False)
            except CancelledError:
                pass
            except Exception as error:
                if self.solving_key == sim.requested_key:
                    self.failed_key = self.solving_key
                    self.error = display_text(f'Emergency analysis failed: {error}. Press the button to retry.')
                    if self.panel:
                        self.panel.pending(self.error)
        if self.enabled and sim.enabled and sim.result and sim.result_key == sim.requested_key and \
                sim.result_key not in (self.report_key, self.failed_key) and not self.future:
            self.cancel = Event()
            self.solving_key = sim.result_key
            self.future = self.pool.submit(self.calculate, sim.result_key, sim.baseline_result, sim.result, self.cancel)

    def focus(self, point, fit=True):
        if not self.current_report:
            return
        point = next(p for p in self.current_report.points if (p.kind, p.node_id) == (point.kind, point.node_id))
        app = self.sim.app
        app.select_node(point.node_id)
        self.selected_target = point.kind, point.node_id
        self.route = self.current_report.route(point)
        self.sim.active_diversion = None
        if fit:
            if self.route:
                from .emergency_rendering import route_paths
                paths = route_paths(app.network, self.route)
                self.sim.fit_points([point.point, self.route.facility.point, *(p for path in paths for p in path)])
            else:
                self.sim.focus_points([point.point])
                from dataclasses import replace
                app.camera = replace(app.camera, x=app.camera.x - app.details.winfo_width() / (2 * app.camera.scale))
            if self.window:
                self.window.withdraw()
        app.invalidate()
        added = point.added_seconds
        app.show_selection_notice(f'EMERGENCY ACCESS / {SERVICE_NAMES[point.kind]}\n{STATUS_NAMES[point.status]}\n' +
                        (f'{point.facility.name} -> Junction {point.number}\nCYAN: full road route / arrows: direction\n' if self.route
                         else 'No current mapped route to this junction.\n') +
                        f'Current road travel: {minutes(point.seconds)}\n'
                        f'Unblocked same-hour baseline: {minutes(point.baseline_seconds)}\n' +
                        (f'Added road travel: {minutes(added)}\n' if added is not None else 'No baseline coverage\n'))
        if point.facility:
            facility = point.facility
            app.detail_text(f'Fastest mapped facility: {facility.name}\n'
                f'Coordinate provenance: {facility.provenance}\nRoad snap distance: {facility.distance_m:.0f}m\n'
                'Dotted cyan: approximate facility-to-road snap.\nOff-road and dispatch time excluded.', True)
        if point.baseline_facility and point.baseline_facility != point.facility:
            app.detail_text(f'Baseline facility: {point.baseline_facility.name}', True)

    def pick(self, x, y):
        if not self.current_report:
            return False
        from .emergency_rendering import visible_risks
        for sx, sy, point in visible_risks(self.sim.app.camera, self.current_report, self.kind):
            if (sx - x) ** 2 + (sy - y) ** 2 <= 64:
                self.focus(point)
                return True
        return False

    def close(self):
        self.cancel.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
