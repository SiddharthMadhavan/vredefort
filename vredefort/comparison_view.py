"""Paired maps driven by the application's existing Tk loop and simulation clock."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import tkinter as tk
import math
import time

import customtkinter as ctk
from PIL import Image, ImageTk

from .comparison import comparison_metrics, format_metric
from .explore_map import ExplorePainter, nearest_node, nearest_road
from .geometry import project
from .presentation import display_text
from .traffic_animation import FlowLayer
from .traffic_rendering import TrafficPainter
from .analysis_scope import selection_roads, selection_target, scope_label


class ComparisonView:
    def __init__(self, simulation):
        self.sim = simulation
        self.app = simulation.app
        self.window = ctk.CTkToplevel(self.app)
        self.window.configure(fg_color='#0c1510')
        self.window.title('Vredefort / Before and after')
        scale = self.window._get_window_scaling()
        width = min(1160, int((self.window.winfo_screenwidth()-80)/scale))
        height = min(820, int((self.window.winfo_screenheight()-140)/scale))
        self.window.geometry(f'{width}x{height}+30+30')
        self.window.minsize(900, 650)
        self.window.protocol('WM_DELETE_WINDOW', self.window.withdraw)
        self.window.bind('<Return>', self.analyze_selection)
        self.window.bind('<Escape>', lambda event: self.app.clear_selection())
        self.window.grid_columnconfigure((0, 1), weight=1, uniform='maps')
        self.window.grid_rowconfigure(3, weight=1)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='comparison-map')
        self.future = None
        self.painted_key = self.display_camera = self.displayed_result_key = None
        self.camera = replace(self.app.camera, width=560, height=400)
        self.painters = (TrafficPainter(), TrafficPainter())
        self.base_painter = ExplorePainter()
        self.images = []
        self.drag_origin = None
        self.dragged = False
        self.closed = False
        self.error = ''
        self.paint_after = 0.
        self.summary_key = None

        bar = ctk.CTkFrame(self.window, fg_color='transparent')
        bar.grid(row=0, column=0, columnspan=2, sticky='ew', padx=12, pady=8)
        self.play = self.app.button(bar, 'Play', self.sim.toggle_play, width=65)
        self.play.pack(side='left', padx=3)
        for text, command, width in (
            ('+', lambda: self.zoom(1), 38), ('−', lambda: self.zoom(-1), 38),
            ('Reset', self.reset, 70), ('Clear blocks', self.sim.clear_blocks, 110),
        ):
            self.app.button(bar, text, command, width=width).pack(side='left', padx=3)
        self.heatmap = self.app.button(bar, 'Heatmap: OFF', self.sim.toggle_heatmap, width=120)
        self.heatmap.pack(side='left', padx=3)
        self.state_label = self.label(bar, '')
        self.state_label.configure(width=245, height=35, wraplength=245, fg_color='#0c1510')
        self.state_label.pack(side='right', padx=5)
        time_bar = ctk.CTkFrame(self.window, fg_color='transparent')
        time_bar.grid(row=1, column=0, columnspan=2, sticky='ew', padx=16)
        self.time_label = self.label(time_bar, '')
        self.time_label.configure(width=225, fg_color='#0c1510')
        self.time_label.pack(side='left', padx=(0, 12))
        self.slider = ctk.CTkSlider(time_bar, from_=0, to=len(self.sim.model.dataset.hours)-1,
            number_of_steps=len(self.sim.model.dataset.hours)-1, command=self.sim.seek,
            progress_color='#527c5a', button_color='#83b98b', height=16)
        self.slider.pack(side='left', fill='x', expand=True)
        for column, text in enumerate(('BEFORE / Baseline · no closures', 'AFTER / Closure scenario')):
            self.label(self.window, text).grid(row=2, column=column, sticky='w', padx=16, pady=8)
        self.canvases, self.items, self.hover_items, self.flows = [], [], [], []
        for column in range(2):
            canvas = tk.Canvas(self.window, bg='#090f0c', highlightthickness=1,
                               highlightbackground='#2a3d30', cursor='fleur', takefocus=True)
            canvas.grid(row=3, column=column, sticky='nsew', padx=(12, 4) if column == 0 else (4, 12))
            self.canvases.append(canvas)
            self.items.append(canvas.create_image(0, 0, anchor='nw'))
            self.hover_items.append(canvas.create_oval(-100, -100, -90, -90,
                                      fill='#b2efb9', outline='#15391f', width=2))
            self.flows.append(FlowLayer(canvas))
            canvas.bind('<Configure>', self.resize)
            canvas.bind('<ButtonPress-1>', self.press)
            canvas.bind('<B1-Motion>', self.drag)
            canvas.bind('<ButtonRelease-1>', self.release)
            canvas.bind('<Motion>', self.hover)
            canvas.bind('<Leave>', self.hide_hover)
            canvas.bind('<MouseWheel>', lambda event: self.zoom(1 if event.delta > 0 else -1, event.x, event.y))
            canvas.bind('<Key-plus>', lambda event: self.zoom(1))
            canvas.bind('<Key-minus>', lambda event: self.zoom(-1))
            for key, dx, dy in (('Left', -80, 0), ('Right', 80, 0), ('Up', 0, -80), ('Down', 0, 80)):
                canvas.bind(f'<{key}>', lambda event, dx=dx, dy=dy: self.pan(dx, dy))
        inspector = ctk.CTkFrame(self.window, fg_color='transparent')
        inspector.configure(height=52)
        inspector.pack_propagate(False)
        inspector.grid(row=4, column=0, columnspan=2, sticky='ew', padx=12, pady=6)
        self.block = self.app.button(inspector, 'Select to block', self.sim.toggle_block, width=150)
        self.block.pack(side='left', padx=3)
        self.app.button(inspector, 'Impacts / routes', self.sim.show_impacts, width=130).pack(side='left', padx=3)
        self.app.button(inspector, 'Fit impacts', self.fit_impacts, width=110).pack(side='left', padx=3)
        self.selection_label = self.label(inspector, 'Click a road or junction on either map')
        self.selection_label.configure(width=330, wraplength=330)
        self.selection_label.pack(side='left', padx=12)
        bottom = ctk.CTkFrame(self.window, fg_color='#0d1711')
        bottom.grid(row=5, column=0, columnspan=2, sticky='ew', padx=12, pady=(0, 8))
        bottom.grid_columnconfigure(0, weight=3)
        bottom.grid_columnconfigure(1, weight=2)
        self.table = ctk.CTkFrame(bottom, fg_color='transparent')
        self.table.grid(row=0, column=0, sticky='nsew', padx=8, pady=5)
        self.table.grid_columnconfigure(0, weight=1)
        self.metric_labels = []
        for row in range(9):
            cells = []
            for column in range(4):
                cell = self.label(self.table, '', color='#b2ceba' if row == 0 else '#819487')
                cell.configure(width=220 if column == 0 else 85, anchor='w' if column == 0 else 'e')
                cell.grid(row=row, column=column, sticky='ew', padx=5)
                cells.append(cell)
            self.metric_labels.append(cells)
        self.facilities = ctk.CTkTextbox(bottom, height=178, font=self.app.small_font,
            text_color='#abd2ad', fg_color='transparent', wrap='word')
        self.facilities.grid(row=0, column=1, sticky='nsew', padx=8, pady=5)
        footer = self.label(self.window, 'Green: low · red: high · gold: extra traffic · cyan: diversion · ×: closed'
                   '   /   '+self.app.config_values['attribution'])
        footer.configure(width=1, wraplength=840, height=36)
        footer.grid(row=6, column=0, columnspan=2, sticky='w', padx=16, pady=(0, 8))

    def label(self, parent, text, color='#abd2ad'):
        return ctk.CTkLabel(parent, text=text, font=self.app.small_font, text_color=color,
                           anchor='w', justify='left', height=19)

    def analyze_selection(self, event=None):
        self.app.lift()
        return self.app.analyze_selected(event)

    def resize(self, event):
        width = min(canvas.winfo_width() for canvas in self.canvases)
        height = min(canvas.winfo_height() for canvas in self.canvases)
        if width > 1 and height > 1:
            self.camera = replace(self.camera, width=width, height=height)

    def reset(self):
        self.camera = replace(self.camera, x=project(77.5946, 12.9716)[0],
                              y=project(77.5946, 12.9716)[1], zoom=11)

    def fit_impacts(self):
        identifiers = self.sim.report.affected_roads
        points = [point for identifier in identifiers
                  for path in self.app.network.roads_by_id[identifier].paths for point in path]
        if not points:
            return
        xs, ys = zip(*points)
        scale = min(max(100, self.camera.width-60)/max(max(xs)-min(xs), 1e-9),
                    max(100, self.camera.height-60)/max(max(ys)-min(ys), 1e-9))
        self.camera = replace(self.camera, x=(min(xs)+max(xs))/2, y=(min(ys)+max(ys))/2,
                              zoom=max(8, min(18, int(math.log2(scale/256)))))

    def zoom(self, delta, x=None, y=None):
        old = self.camera
        level = max(8, min(18, old.zoom + delta))
        x, y = old.width/2 if x is None else x, old.height/2 if y is None else y
        world = old.world(x, y)
        new = replace(old, zoom=level)
        self.camera = replace(new, x=world[0]-(x-old.width/2)/new.scale,
                              y=world[1]-(y-old.height/2)/new.scale)

    def pan(self, dx, dy):
        self.camera = replace(self.camera, x=self.camera.x+dx/self.camera.scale,
                              y=max(0, min(1, self.camera.y+dy/self.camera.scale)))

    def press(self, event):
        event.widget.focus_set()
        self.drag_origin = event.x, event.y, self.camera
        self.dragged = False

    def drag(self, event):
        if not self.drag_origin:
            return
        x, y, old = self.drag_origin
        dx, dy = event.x-x, event.y-y
        if abs(dx)+abs(dy) > 4:
            self.dragged = True
        if not self.dragged:
            return
        self.camera = replace(old, x=old.x-dx/old.scale, y=max(0, min(1, old.y-dy/old.scale)))
        self.paint_after = time.perf_counter()+.06
        if self.display_camera and self.display_camera.zoom == old.zoom:
            offset = self.camera.screen((self.display_camera.x, self.display_camera.y))
            for canvas, item, flow in zip(self.canvases, self.items, self.flows):
                canvas.coords(item, offset[0]-old.width/2, offset[1]-old.height/2)
                flow.hide()
        self.hide_hover()

    def release(self, event):
        if self.drag_origin and not self.dragged:
            if getattr(event, 'state', 0) & 1:
                road = nearest_road(self.app.network, self.camera, event.x, event.y)
                if road:
                    self.app.toggle_area_road(road.id)
            else:
                node = nearest_node(self.app.network, self.camera, event.x, event.y)
                road = nearest_road(self.app.network, self.camera, event.x, event.y) if not node else None
                if node:
                    self.app.select_node(node['id'])
                elif road:
                    self.app.select_road(road.id)
                else:
                    self.app.clear_selection()
        self.drag_origin = None

    def hide_hover(self, event=None):
        for canvas, item in zip(self.canvases, self.hover_items):
            canvas.coords(item, -100, -100, -90, -90)

    def hover(self, event):
        if self.drag_origin:
            return
        node = nearest_node(self.app.network, self.camera, event.x, event.y)
        self.hide_hover()
        if node:
            x, y = self.camera.screen(node['point'])
            for canvas, item in zip(self.canvases, self.hover_items):
                canvas.coords(item, x-5, y-5, x+5, y+5)
                canvas.tag_raise(item)

    def update_summary(self):
        sim = self.sim
        for cells in self.metric_labels:
            for cell in cells:
                cell.configure(text='')
        for cell, text in zip(self.metric_labels[0], ('NETWORK COMPARISON', 'Before', 'After', 'Change')):
            cell.configure(text=text)
        for cells, metric in zip(self.metric_labels[1:], comparison_metrics(sim.baseline_result, sim.result, sim.report)):
            labels = {'Mean congestion · common open roads': 'Mean congestion · open roads',
                      'Heavy roads · common open roads (70%+)': 'Heavy roads · open (70%+)',
                      'Roads receiving extra traffic': 'Extra-loaded roads',
                      'Nearby facilities · potential access delay': 'Facilities · access flags'}
            unit = '%' if metric.unit == '%' else ''
            label = labels.get(metric.label, metric.label) + (' (veh/h)' if metric.unit == 'veh/h' else '')
            for cell, text in zip(cells, (label, format_metric(metric.before, unit),
                    format_metric(metric.after, unit), format_metric(metric.change, unit, signed=True))):
                cell.configure(text=text)
        lines = ['NEARBY FACILITIES / POTENTIAL ACCESS DELAY',
                 f'Within {sim.report.radius_m:.0f}m of closed or extra-loaded roads. No outage or measured delay inferred.', '']
        lines += [f'{facility.name} / {facility.facility_type} / {facility.distance_m:.0f}m / '
                  f'{"closure" if facility.near_closed else "extra traffic"}' for facility in sim.report.facilities]
        if not sim.report.facilities:
            lines.append('No mapped facilities within the impact buffer.')
        lines += ['', 'Demand and congestion are model estimates; no physical queues. '
                  'Detours use an undirected graph; turn permissions are unknown.',
                  f'Assignment: {"converged" if sim.result.converged else "approximate / not converged"}.']
        self.facilities.configure(state='normal')
        self.facilities.delete('1.0', 'end')
        self.facilities.insert('1.0', '\n'.join(lines))
        self.facilities.configure(state='disabled')

    def tick(self, now):
        if self.closed or not self.window.winfo_exists() or self.window.state() == 'withdrawn':
            return
        sim = self.sim
        def set_text(widget, text):
            if widget.cget('text') != text:
                widget.configure(text=text)
        set_text(self.play, 'Pause' if sim.running else 'Play')
        set_text(self.heatmap, f'Heatmap: {"ON" if sim.heatmap_enabled else "OFF"}')
        if self.slider.get() != sim.clock_s//3600:
            self.slider.set(sim.clock_s//3600)
        # Labels and metrics correspond to the paired images actually displayed.
        pending = self.displayed_result_key != sim.requested_key
        error = self.error or (sim.status.cget('text') if sim.failed_key == sim.requested_key else '')
        set_text(self.state_label, display_text(error) if error else 'Updating / previous pair' if pending else 'Same hour · linked cameras')
        if self.displayed_result_key:
            set_text(self.time_label, sim.model.dataset.hours[self.displayed_result_key[0]][:16]+' / IST assumed')
        set_text(self.block, sim.block_button.cget('text'))
        if self.block.cget('state') != sim.block_button.cget('state'):
            self.block.configure(state=sim.block_button.cget('state'))
        selection = self.app.selection
        text = 'Click a road or junction on either map'
        if selection:
            kind, identifier = selection
            text = f'ROAD / {identifier}' if kind == 'road' else scope_label(self.app.network, selection_target(selection))
            if kind == 'road' and self.displayed_result_key == sim.result_key:
                before, after = sim.baseline_result.links[identifier], sim.result.links[identifier]
                text += f'\n{before.flow:,.0f} → {after.flow:,.0f} veh/h / {before.speed:.0f} → {after.speed:.0f} km/h'
        set_text(self.selection_label, text)
        keys = self.camera.tile_keys()
        tiles = {}
        if self.app.tiles:
            self.app.tiles.request(keys, viewer='comparison')
            tiles = self.app.tiles.snapshot(keys)
        route = sim.active_diversion.route.edge_ids if sim.active_diversion else None
        key = (self.camera, sim.result_key, selection, sim.heatmap_enabled, route,
               tuple((key, id(tile)) for key, tile in tiles.items()))
        if self.future and self.future.done():
            future, self.future = self.future, None
            try:
                rendered_key, frames = future.result()
                if rendered_key == key:
                    self.images = [ImageTk.PhotoImage(frame[0], master=self.window) for frame in frames]
                    for canvas, item, image, flow, frame in zip(self.canvases, self.items, self.images, self.flows, frames):
                        canvas.itemconfigure(item, image=image)
                        canvas.coords(item, 0, 0)
                        flow.install(self.camera, frame[1], sim.elapsed)
                    self.painted_key, self.display_camera = key, self.camera
                    self.displayed_result_key = sim.result_key
                    if self.summary_key != sim.result_key:
                        self.update_summary()
                        self.summary_key = sim.result_key
                    self.error = ''
            except Exception as error:
                self.error = f'Comparison map unavailable: {error}'
                self.painted_key = key
        if not self.future and key != self.painted_key and now >= self.paint_after:
            camera, network, datasets = self.camera, self.app.network, sim.datasets
            baseline, scenario, report, diversion = sim.baseline_result, sim.result, sim.report, sim.active_diversion
            heatmap = sim.heatmap_enabled
            def paint():
                base = self.base_painter.paint(camera, tiles, network, selection).convert('RGBA')
                frames = []
                for index, result in enumerate((baseline, scenario)):
                    overlay, paths = self.painters[index].frame(camera, datasets['views']['KML road graph'], result,
                        selected=selection_roads(network, selection),
                        impact=report if index else None, diversion=diversion if index else None,
                        datasets=datasets, heatmap=heatmap)
                    frames.append((Image.alpha_composite(base, overlay), paths))
                return key, frames
            self.future = self.pool.submit(paint)
        for flow in self.flows:
            flow.draw(self.camera, sim.elapsed, enabled=self.display_camera == self.camera)

    def close(self):
        self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)
