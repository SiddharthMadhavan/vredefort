"""Synthetic playback alongside the explorer and agents, on the same Tk loop."""
from concurrent.futures import ThreadPoolExecutor, CancelledError
from dataclasses import replace
from threading import Event
import time

import customtkinter as ctk
from PIL import Image, ImageTk

from .data import DATA
from .impact_panel import ImpactPanel
from .impacts import build_impact_report
from .simulation_data import load_simulation_data
from .traffic_animation import FlowLayer
from .traffic_rendering import TrafficPainter
from .presentation import display_text
from .analysis_scope import selection_roads


class SimulationController:
    def __init__(self, app, parent):
        self.app = app
        self.enabled = self.running = False
        self.heatmap_enabled = False
        self.model = self.datasets = self.result = self.report = None
        self.baseline_result = self.comparison = None
        self.load_future = self.solve_future = self.paint_future = None
        self.cancel = Event()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='traffic-model')
        self.paint_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='traffic-glow')
        self.clock_s, self.speed, self.elapsed = 0., 300., 0.
        self.last_tick = time.perf_counter()
        self.blocked_edges, self.blocked_nodes = set(), set()
        self.requested_key = self.result_key = self.failed_key = self.painted_key = None
        self.active_diversion = None
        self.painter = TrafficPainter()
        self.bitmap = self.image = self.bitmap_camera = None
        self.fade_from = self.fade_to = None
        self.fade_started = 0.
        self.error = ''
        self.impact_window = self.impact_panel = None
        self.item = app.canvas.create_image(0, 0, anchor='nw', state='hidden')
        self.flow = FlowLayer(app.canvas)
        self.frame = ctk.CTkFrame(parent, fg_color='transparent')
        self.frame.grid_columnconfigure((0, 1), weight=1)

        def label(text, row, color='#819487'):
            widget = ctk.CTkLabel(self.frame, text=text, font=app.small_font,
                                 text_color=color, anchor='w', justify='left', wraplength=250)
            widget.grid(row=row, column=0, columnspan=2, sticky='ew', padx=4, pady=2)
            return widget

        self.legend = label('GREEN: LOW · RED: HIGH', 0)
        self.time_label = label('Loading traffic...', 1, '#abd2ad')
        self.slider = ctk.CTkSlider(self.frame, from_=0, to=167, number_of_steps=167,
                                   command=self.seek, state='disabled', height=16,
                                   progress_color='#527c5a', button_color='#83b98b')
        self.slider.set(0)
        self.slider.grid(row=2, column=0, columnspan=2, sticky='ew', padx=6, pady=3)
        self.play_button = app.button(self.frame, 'Play', self.toggle_play, width=112, state='disabled')
        self.play_button.grid(row=3, column=0, padx=3, pady=3, sticky='ew')
        self.speed_picker = ctk.CTkOptionMenu(
            self.frame, values=['60x', '300x', '900x', '3600x'], command=self.set_speed,
            font=app.small_font, dropdown_font=app.small_font, width=112,
            fg_color='#15251a', button_color='#3d5943', text_color='#abd2ad')
        self.speed_picker.set('300x')
        self.speed_picker.grid(row=3, column=1, padx=3, pady=3, sticky='ew')
        self.block_button = app.button(self.frame, 'Select to block', self.toggle_block,
                                        width=112, state='disabled')
        self.block_button.grid(row=4, column=0, padx=3, pady=3, sticky='ew')
        app.button(self.frame, 'Clear blocks', self.clear_blocks, width=112).grid(
            row=4, column=1, padx=3, pady=3, sticky='ew')
        self.impact_button = app.button(self.frame, 'Impacts / routes', self.show_impacts,
                                         width=112, state='disabled')
        self.impact_button.grid(row=5, column=0, padx=3, pady=3, sticky='ew')
        self.heatmap_button = app.button(self.frame, 'Heatmap: OFF', self.toggle_heatmap, width=112)
        self.heatmap_button.grid(row=5, column=1, padx=3, pady=3, sticky='ew')
        self.compare_button = app.button(self.frame, 'Compare before / after', self.show_comparison, state='disabled')
        self.compare_button.grid(row=6, column=0, columnspan=2, sticky='ew', padx=3, pady=3)
        self.status = label('Loading traffic...', 7)

    def set_enabled(self, enabled):
        self.enabled = enabled
        if enabled:
            self.frame.pack(fill='x', padx=12, pady=(0, 6), before=self.app.detail_title)
            if not self.model and not self.load_future:
                self.error = ''
                self.status.configure(text='Loading traffic...')
                self.load_future = self.pool.submit(load_simulation_data, self.app.network)
        else:
            self.running = False
            self.cancel.set()
            self.play_button.configure(text='Play')
            self.frame.pack_forget()
            self.flow.hide()
            self.app.canvas.itemconfigure(self.item, state='hidden')
            if self.impact_window:
                self.impact_window.withdraw()
            if self.comparison:
                self.comparison.window.withdraw()
        self.last_tick = time.perf_counter()
        self.selection_changed()
        self.app.resize_detail_body()
        self.app.after_idle(self.app.resize_detail_body)

    def selection_changed(self):
        target = self.app.selection
        ready = self.enabled and self.model is not None and target is not None
        if ready:
            kind, identifier = target
            blocked = set(identifier) <= self.blocked_edges if kind == 'area' else identifier in (
                self.blocked_edges if kind == 'road' else self.blocked_nodes)
            text = f'{"Unblock" if blocked else "Block"} {"road" if kind == "road" else "area" if kind == "area" else "junction"}'
        else:
            text = 'Select to block'
        self.block_button.configure(text=text, state='normal' if ready else 'disabled')

    def seek(self, value):
        if self.model:
            hour = max(0, min(len(self.model.dataset.hours) - 1, round(float(value))))
            self.clock_s = hour * 3600.
            self.request()

    def set_speed(self, value):
        self.speed = float(value.rstrip('x'))

    def toggle_heatmap(self):
        self.heatmap_enabled = not self.heatmap_enabled
        self.heatmap_button.configure(text=f'Heatmap: {"ON" if self.heatmap_enabled else "OFF"}',
                                      fg_color='#33533c' if self.heatmap_enabled else '#15251a')

    def toggle_play(self):
        if self.model:
            if self.clock_s >= len(self.model.dataset.hours) * 3600 - 1:
                self.clock_s = 0.
            self.running = not self.running
            self.play_button.configure(text='Pause' if self.running else 'Play')

    def toggle_block(self):
        if self.model and self.app.selection:
            kind, identifier = self.app.selection
            if kind == 'area':
                if set(identifier) <= self.blocked_edges:
                    self.blocked_edges.difference_update(identifier)
                else:
                    self.blocked_edges.update(identifier)
            else:
                group = self.blocked_edges if kind == 'road' else self.blocked_nodes
                group.remove(identifier) if identifier in group else group.add(identifier)
            self.active_diversion = None
            self.failed_key = None
            self.request()
            self.selection_changed()

    def clear_blocks(self):
        self.blocked_edges.clear()
        self.blocked_nodes.clear()
        self.active_diversion = None
        self.failed_key = None
        self.request()
        self.selection_changed()

    def request(self):
        if not self.model:
            return
        hour = min(int(self.clock_s // 3600), len(self.model.dataset.hours) - 1)
        key = (hour, frozenset(self.blocked_edges), frozenset(self.blocked_nodes))
        if key != self.requested_key:
            self.cancel.set()
            self.requested_key = key
            self.active_diversion = None
            self.status.configure(text='Calculating scenario / previous frame retained')
            self.impact_button.configure(state='disabled')
            closed = {edge['id'] for edge in self.model.edges if edge['id'] in self.blocked_edges
                      or edge['source'] in self.blocked_nodes or edge['target'] in self.blocked_nodes}
            self.flow.set_blocked(closed)
            if self.impact_window:
                self.impact_window.withdraw()
        text = self.model.dataset.hours[hour][:16] + ' / IST assumed'
        if self.time_label.cget('text') != text:
            self.time_label.configure(text=text)
        if self.slider.get() != hour:
            self.slider.set(hour)

    def solve(self, key, cancel):
        baseline = self.model.solve(key[0], cancel_event=cancel)
        result = self.model.solve(*key, cancel_event=cancel) if key[1] or key[2] else baseline
        report = build_impact_report(self.model, result, self.datasets, key[1], cancel)
        return key, baseline, result, report

    def paint_key(self):
        route = self.active_diversion.route.edge_ids if self.active_diversion else None
        return self.app.camera, self.result_key, self.app.selection, route, self.heatmap_enabled

    def display(self, bitmap):
        self.bitmap = bitmap
        self.image = ImageTk.PhotoImage(bitmap, master=self.app)
        self.app.canvas.itemconfigure(self.item, image=self.image, state='normal' if self.enabled else 'hidden')
        self.app.canvas.coords(self.item, 0, 0)

    def summary(self):
        r = self.result
        self.status.configure(text=(f'{len(self.blocked_edges)} roads / {len(self.blocked_nodes)} junctions blocked\n'
                                   f'Rerouted {r.rerouted_demand:,.0f} / unmet {r.unmet_demand:,.0f} veh/h' +
                                   (' / approximate' if not r.converged else '')))
        self.compare_button.configure(state='normal')
        self.impact_button.configure(state='normal' if self.report.closed_roads else 'disabled')
        self.app.after_idle(self.app.resize_detail_body)
        if self.app.selection and self.app.selection[0] == 'road':
            self.app.show_simulation_details(self.app.selection[1])
        elif self.app.selection and self.app.selection[0] == 'area':
            self.app.show_area_simulation_details()

    def tick(self, now):
        dt = max(0., min(.2, now - self.last_tick))
        self.last_tick = now
        if self.load_future and self.load_future.done():
            future, self.load_future = self.load_future, None
            try:
                self.datasets, self.model = future.result()
                self.slider.configure(to=len(self.model.dataset.hours) - 1,
                                      number_of_steps=len(self.model.dataset.hours) - 1, state='normal')
                self.play_button.configure(state='normal')
                self.request()
                self.selection_changed()
            except Exception as error:
                self.error = display_text(f'Simulation unavailable: {error}')
                self.status.configure(text=self.error + '\nSwitch modes to retry.')
        if self.solve_future and self.solve_future.done():
            future, self.solve_future = self.solve_future, None
            try:
                key, baseline, result, report = future.result()
                if key == self.requested_key:
                    self.result_key, self.result, self.report = key, result, report
                    self.baseline_result = baseline
                    self.summary()
            except CancelledError:
                pass
            except Exception as error:
                if self.solving_key == self.requested_key:
                    self.failed_key = self.solving_key
                    self.status.configure(text=display_text(f'Scenario failed: {error}\nChange hour or blocks to retry.'))
                    self.running = False
                    self.play_button.configure(text='Play')
        if not self.enabled:
            return
        if self.model:
            if self.running:
                # Keep trails moving while the next assignment is calculated;
                # only the dataset playback clock waits for the new scenario.
                self.elapsed += dt
            if self.running and self.result_key == self.requested_key and self.failed_key != self.requested_key:
                self.clock_s = min(len(self.model.dataset.hours) * 3600 - 1, self.clock_s + dt * self.speed)
                if self.clock_s >= len(self.model.dataset.hours) * 3600 - 1:
                    self.running = False
                    self.play_button.configure(text='Play')
            self.request()
            if not self.solve_future and self.requested_key not in (self.result_key, self.failed_key):
                self.cancel = Event()
                self.solving_key = self.requested_key
                self.solve_future = self.pool.submit(self.solve, self.solving_key, self.cancel)
        if not self.result:
            return
        key = self.paint_key()
        if self.paint_future and self.paint_future.done():
            future, self.paint_future = self.paint_future, None
            try:
                painted_key, bitmap, paths = future.result()
                if painted_key == key:
                    camera = key[0]
                    if camera == self.bitmap_camera and self.bitmap is not None:
                        self.fade_from, self.fade_to, self.fade_started = self.bitmap, bitmap, now
                    else:
                        self.fade_from = self.fade_to = None
                        self.display(bitmap)
                    self.bitmap_camera, self.painted_key = camera, key
                    self.flow.install(camera, paths, self.elapsed)
                    self.app.canvas.tag_raise(self.app.hover_item)
            except Exception as error:
                self.painted_key = key
                self.status.configure(text=display_text(f'Traffic painting failed: {error}'))
        if not self.paint_future and key != self.painted_key and now >= self.app.paint_after:
            result, report, selected, diversion = self.result, self.report, self.app.selection, self.active_diversion
            camera = self.app.camera
            heatmap = self.heatmap_enabled
            view = self.datasets['views']['KML road graph']
            def paint():
                bitmap, paths = self.painter.frame(camera, view, result,
                    selected=selection_roads(self.app.network, selected),
                    impact=report, diversion=diversion, datasets=self.datasets, heatmap=heatmap)
                return key, bitmap, paths
            self.paint_future = self.paint_pool.submit(paint)
        if self.fade_to is not None and self.bitmap_camera == self.app.camera:
            progress = min(1., (now - self.fade_started) / .65)
            eased = progress * progress * (3 - 2 * progress)
            self.display(self.fade_to if progress == 1 else Image.blend(self.fade_from, self.fade_to, eased))
            if progress == 1:
                self.fade_from = self.fade_to = None
        state = 'normal' if self.bitmap_camera == self.app.camera else 'hidden'
        if self.app.canvas.itemcget(self.item, 'state') != state:
            self.app.canvas.itemconfigure(self.item, state=state)
        self.flow.draw(self.app.camera, self.elapsed)

    def show_impacts(self):
        if not self.report or not self.report.closed_roads or self.result_key != self.requested_key:
            return
        if self.impact_window is None or not self.impact_window.winfo_exists():
            self.impact_window = ctk.CTkToplevel(self.app)
            self.impact_window.title('CityCollapse / Closure impacts')
            self.impact_window.geometry('390x760')
            self.impact_window.minsize(370, 520)
            self.impact_window.protocol('WM_DELETE_WINDOW', self.impact_window.withdraw)
            self.impact_panel = ImpactPanel(
                self.impact_window, self.app.font, self.app.small_font,
                self.focus_road, self.focus_facility, self.preview_route,
                self.fit_impacts, self.impact_window.withdraw)
            self.impact_panel.pack(fill='both', expand=True)
            self.impact_window.bind('<Configure>', lambda event: self.impact_panel.schedule_fit())
        self.impact_panel.set_report(self.report, self.result)
        self.impact_window.deiconify()
        self.impact_window.lift()

    def focus_points(self, points):
        xs, ys = zip(*points)
        self.app.camera = replace(self.app.camera, x=(min(xs) + max(xs)) / 2,
                                  y=(min(ys) + max(ys)) / 2, zoom=15)
        self.app.update_zoom_buttons()
        self.app.invalidate()

    def focus_road(self, identifier):
        self.app.select_road(identifier)
        self.focus_points([p for path in self.app.network.roads_by_id[identifier].paths for p in path])

    def focus_facility(self, facility):
        self.app.clear_selection()
        point = self.datasets[facility.kind][facility.index]
        self.focus_points([point['point']])
        self.app.detail_title.configure(text=facility.name)
        self.app.clear_body()
        self.app.detail_text(f'{facility.kind.upper()}\n{facility.distance_m:.0f}m from affected road\nPotential access delay; no outage inferred.')
        self.app.detail_text(f'Coordinate provenance: {point.get("match_status", "supplied dataset")}\n'
                             f'Address: {point.get("Address") or point.get("matched_address") or "Unavailable"}', True)

    def preview_route(self, option):
        self.active_diversion = option
        self.fit_roads(option.route.edge_ids)

    def fit_roads(self, identifiers):
        import math
        points = [p for identifier in identifiers for path in self.app.network.roads_by_id[identifier].paths for p in path]
        if not points:
            return
        xs, ys = zip(*points)
        # Reserve the left detail panel when fitting a route.
        available_width = max(100, self.app.camera.width - self.app.details.winfo_width() - 60)
        scale = min(available_width / max(max(xs) - min(xs), 1e-9),
                    max(100, self.app.camera.height - 80) / max(max(ys) - min(ys), 1e-9))
        zoom = max(8, min(18, int(math.log2(scale / 256))))
        self.app.camera = replace(self.app.camera, x=(min(xs) + max(xs)) / 2,
                                  y=(min(ys) + max(ys)) / 2, zoom=zoom)
        self.app.camera = replace(self.app.camera, x=self.app.camera.x - self.app.details.winfo_width() / (2 * self.app.camera.scale))
        self.app.update_zoom_buttons()
        self.app.invalidate()

    def fit_impacts(self):
        if self.report:
            identifiers = self.report.affected_roads | {edge for option in self.report.diversions for edge in option.route.edge_ids}
            self.fit_roads(identifiers)

    def show_model(self):
        self.app.clear_body()
        self.app.detail_title.configure(text='TRAFFIC MODEL')
        self.app.detail_text(display_text((DATA / 'traffic-model.txt').read_text(encoding='utf-8')))

    def show_comparison(self):
        if self.baseline_result is None:
            return
        if self.comparison is None:
            from .comparison_view import ComparisonView
            self.comparison = ComparisonView(self)
        self.comparison.window.deiconify()
        self.comparison.window.lift()

    def close(self):
        if self.comparison:
            self.comparison.close()
        self.cancel.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.paint_pool.shutdown(wait=False, cancel_futures=True)
