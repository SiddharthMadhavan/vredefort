from concurrent.futures import ThreadPoolExecutor, CancelledError
import ctypes
from dataclasses import replace
import sys
import time
import tkinter as tk
from tkinter import font as tkfont
import webbrowser
from queue import Queue, Empty
from threading import Thread

import customtkinter as ctk
from PIL import ImageTk

from .config import settings, analyst_settings
from .geometry import project
from .map_renderer import Camera, FONT_FILE, TileCache
from .explore_map import load_network, nearest_node, nearest_road, paint_explore
from .live_traffic import AnalysisCancel, sample_road
from .analyst_panel import AnalystPanel
from .traffic_agents import TrafficAnalysts

BG, FG, BORDER = '#0c1510', '#abd2ad', '#3d5943'
CENTRE = project(77.5946, 12.9716)


class CityCollapseApp(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode('dark')
        ctk.set_default_color_theme('green')
        if sys.platform == 'win32' and FONT_FILE.exists():
            ctypes.windll.gdi32.AddFontResourceExW(str(FONT_FILE), 0x10, 0)
        super().__init__()
        self.title('CityCollapse / Road explorer')
        scale = self._get_window_scaling()
        width = min(1400, int((self.winfo_screenwidth() - 80) / scale))
        height = min(900, int((self.winfo_screenheight() - 140) / scale))
        self.geometry(f'{width}x{height}+40+30')
        self.minsize(760, 520)
        self.configure(fg_color=BG)
        self.font_name = 'VT323' if 'VT323' in tkfont.families(self) else 'Courier New'
        self.font = ctk.CTkFont(self.font_name, 20)
        self.small_font = ctk.CTkFont(self.font_name, 17)
        self.closed = False
        self.agent_events = Queue()
        self.agent_cancel = AnalysisCancel()
        self.agent_thread = None
        self.agent_generation = 0
        self.agent_busy = False
        self.agent_target = None
        self.agent_factory = TrafficAnalysts
        self.network = self.selection = self.drag_origin = None
        self.dragged = False
        self.camera = Camera(*CENTRE, 11, width, height)
        self.render_generation, self.dirty = 0, True
        self.render_future = self.map_image = self.display_camera = None
        self.paint_after = 0
        self.dataset_error = self.render_error = ''
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='map-paint')
        self.data_future = self.worker.submit(load_network)
        self.tiles = None
        try:
            self.config_values = settings()
            self.tiles = TileCache(self.config_values['tile_url'])
            self.configuration_error = ''
        except ValueError as error:
            self.config_values = {'attribution': '\u00a9 OpenStreetMap contributors \u00b7 \u00a9 CARTO'}
            self.configuration_error = str(error)
        self._build_widgets()
        self.bind('<Escape>', lambda event: self.clear_selection())
        self.bind('<Return>', self.analyze_selected)
        self.bind('<KP_Enter>', self.analyze_selected)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after_id = self.after(33, self.tick)

    def button(self, parent, text, command, **kwargs):
        return ctk.CTkButton(
            parent, text=text, command=command, font=self.font, text_color=FG,
            fg_color='#15251a', hover_color='#233d29', border_width=1,
            border_color=BORDER, corner_radius=3, height=32, **kwargs)

    def _build_widgets(self):
        self.map_area = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.map_area.place(x=0, y=0, relwidth=1, relheight=1)
        self.canvas = tk.Canvas(self.map_area, background=BG, highlightthickness=0, cursor='fleur')
        self.canvas.pack(fill='both', expand=True)
        self.base_item = self.canvas.create_image(0, 0, anchor='nw')
        self.hover_item = self.canvas.create_oval(
            -100, -100, -90, -90, fill='#8ae8a9', outline='#e0ffe9', width=2)
        for sequence, callback in [
            ('<Configure>', self.resize), ('<ButtonPress-1>', self.press),
            ('<B1-Motion>', self.drag), ('<ButtonRelease-1>', self.release),
            ('<Motion>', self.hover)]:
            self.canvas.bind(sequence, callback)
        self.canvas.bind('<Leave>', lambda event: self.hide_hover())
        self.canvas.bind('<MouseWheel>', lambda event: self.zoom(
            1 if event.delta > 0 else -1, event.x, event.y))
        self.canvas.bind('<Button-4>', lambda event: self.zoom(1, event.x, event.y))
        self.canvas.bind('<Button-5>', lambda event: self.zoom(-1, event.x, event.y))
        self.canvas.bind('<Key-plus>', lambda event: self.zoom(1))
        self.canvas.bind('<Key-equal>', lambda event: self.zoom(1))
        self.canvas.bind('<Key-minus>', lambda event: self.zoom(-1))
        for key, dx, dy in [('Left', -100, 0), ('Right', 100, 0),
                            ('Up', 0, -100), ('Down', 0, 100)]:
            self.canvas.bind(f'<{key}>', lambda event, dx=dx, dy=dy: self.pan_keyboard(dx, dy))
        self.details = ctk.CTkFrame(
            self.map_area, width=300, fg_color=BG, border_width=1,
            border_color=BORDER, corner_radius=4)
        self.details.place(x=16, y=16)
        ctk.CTkLabel(self.details, text='CITYCOLLAPSE_', text_color=FG,
                     font=ctk.CTkFont(self.font_name, 28)).pack(
                         anchor='w', padx=16, pady=(12, 0))
        ctk.CTkLabel(self.details, text='BENGALURU / ROAD EXPLORER',
                     font=self.small_font, text_color='#7eaf87').pack(
                         anchor='w', padx=16, pady=(0, 12))
        self.detail_title = ctk.CTkLabel(
            self.details, text='Select a road or node', font=self.font,
            text_color=FG, wraplength=266, justify='left')
        self.detail_title.pack(anchor='w', padx=16, pady=(0, 6))
        self.detail_body = ctk.CTkScrollableFrame(
            self.details, width=266, height=270, fg_color='transparent',
            corner_radius=0, scrollbar_button_color=BORDER)
        self.detail_body.pack(padx=10, pady=(0, 6))
        self.clear_button = self.button(
            self.details, 'Clear selection [Esc]', self.clear_selection,
            width=266, state='disabled')
        self.clear_button.pack(padx=16, pady=(0, 12))
        self.show_hint()
        self.controls = ctk.CTkFrame(
            self.map_area, fg_color=BG, corner_radius=4, border_width=1, border_color=BORDER)
        self.controls.place(relx=1, x=-16, y=16, anchor='ne')
        self.zoom_in_button = self.button(self.controls, '+', lambda: self.zoom(1), width=38)
        self.zoom_out_button = self.button(self.controls, '-', lambda: self.zoom(-1), width=38)
        for button in (self.zoom_in_button, self.zoom_out_button):
            button.pack(side='left', padx=3, pady=5)
        self.button(self.controls, 'Reset', self.reset_camera, width=64).pack(
            side='left', padx=3, pady=5)
        self.button(self.controls, 'Retry map', self.retry_tiles, width=88).pack(
            side='left', padx=3, pady=5)
        self.status = ctk.CTkLabel(
            self.map_area, text='Loading roads...', font=self.small_font, fg_color=BG,
            text_color='#9bbca1', corner_radius=2, wraplength=420, justify='left')
        self.status.place(x=16, rely=1, y=-12, anchor='sw')
        self.attribution = ctk.CTkLabel(
            self.map_area, text=self.config_values['attribution'], fg_color=BG,
            font=ctk.CTkFont(self.font_name, 15), text_color='#819487', cursor='hand2')
        self.attribution.place(relx=1, rely=1, x=-16, y=-12, anchor='se')
        self.attribution.bind('<Button-1>', lambda event: webbrowser.open(
            'https://www.openstreetmap.org/copyright'))
        self.analyst_panel = AnalystPanel(self, self.font, self.small_font, self.close_analyst)

    def clear_body(self):
        for widget in self.detail_body.winfo_children():
            widget.destroy()
        self.detail_body._parent_canvas.yview_moveto(0)

    def detail_text(self, text, muted=False):
        ctk.CTkLabel(
            self.detail_body, text=text, font=self.small_font,
            text_color='#819487' if muted else FG, wraplength=252,
            justify='left', anchor='w').pack(fill='x', padx=4, pady=4)

    def show_hint(self):
        self.clear_body()
        self.detail_text('Click a road to inspect its edge.\nClick a node to inspect its connections.')
        self.detail_text('Drag to pan. Scroll or use +/- to zoom.\nNodes appear when you zoom closer.', True)
        self.detail_text('Select a road, then press Enter for Live and Historical Traffic Analysts.', True)

    def select_road(self, identifier):
        network = self.network
        if network is None:
            return
        road = network.roads_by_id[identifier]
        p = road.properties
        self.selection = ('road', identifier)
        self.selection_changed()
        self.detail_title.configure(text='ROAD / EDGE')
        self.clear_body()
        self.detail_text(f'ID\n{identifier}\n\nLength\n{p["length_m"]:,.1f} m')
        if p.get('names'):
            self.detail_text('Name\n' + ', '.join(p['names']))
        for label, node_id in [('Start node', p['source']), ('End node', p['target'])]:
            node = network.nodes_by_id[node_id]
            self.detail_text(f'{label}\n{node_id}')
            self.button(self.detail_body, f'Inspect node {node["number"]}',
                        lambda node_id=node_id: self.select_node(node_id),
                        width=250).pack(padx=4, pady=4)
        self.detail_text('Source: existing KML road graph.\nConnectivity inferred from dataset coordinates.', True)
        self.button(self.detail_body, 'Analyze traffic [Enter]', self.analyze_selected,
                    width=250).pack(padx=4, pady=6)
        self.clear_button.configure(state='normal')
        self.invalidate()

    def select_node(self, identifier):
        network = self.network
        if network is None:
            return
        node = network.nodes_by_id[identifier]
        self.selection = ('node', identifier)
        self.selection_changed()
        self.detail_title.configure(text=f'NODE {node["number"]}')
        self.clear_body()
        lon, lat = node['coordinate']
        self.detail_text(
            f'ID\n{identifier}\n\nKind\n{node["kind"].replace("_", " ")}'
            f'\n\nLongitude / latitude\n{lon:.6f}, {lat:.6f}'
            f'\n\nDegree\n{node["degree"]}')
        edges = network.edge_ids[identifier]
        self.detail_text(f'Connected edges ({len(edges)})')
        for edge_id in edges:
            button = self.button(
                self.detail_body, edge_id,
                lambda edge_id=edge_id: self.select_road(edge_id), width=250)
            button.configure(font=ctk.CTkFont(self.font_name, 15))
            button.pack(padx=4, pady=3)
        self.detail_text('Source: existing KML road graph.\nJunction topology is inferred, not surveyed.', True)
        self.clear_button.configure(state='normal')
        self.invalidate()

    def clear_selection(self):
        self.selection = None
        self.selection_changed()
        self.hide_hover()
        self.detail_title.configure(text='Select a road or node')
        self.show_hint()
        self.clear_button.configure(state='disabled')
        self.invalidate()

    def selection_changed(self):
        if self.agent_target and self.selection != ('road', self.agent_target):
            self.agent_cancel.set()
            self.agent_generation += 1
            self.agent_busy = False
            self.agent_target = None
            for agent in ('live', 'historical'):
                self.analyst_panel.set_status('Selection changed / select a road and press Enter', agent=agent)

    def analyze_selected(self, event=None):
        if self.network is None or not self.selection or self.selection[0] != 'road':
            self.status.configure(text='Select a road, then press Enter to analyze traffic.')
            return 'break'
        if self.agent_thread and self.agent_thread.is_alive():
            self.analyst_panel.set_status('Analysis in progress; a cancelled request may take a moment to stop.')
            return 'break'
        road_id = self.selection[1]
        self.agent_generation += 1
        generation = self.agent_generation
        self.agent_cancel = AnalysisCancel()
        cancel = self.agent_cancel
        self.agent_target = road_id
        self.agent_busy = True
        was_open = bool(self.analyst_panel.place_info())
        self.map_area.place_configure(relwidth=.5)
        self.analyst_panel.place(relx=.5, rely=0, relwidth=.5, relheight=1)
        for button in self.controls.winfo_children():
            button.pack_configure(side='top', fill='x')
        self.controls.place_configure(relx=1, rely=1, x=-16, y=-106, anchor='se')
        self.status.place_configure(y=-66)
        if not was_open:
            self.after(100, self.focus_analyzed_road)
        try:
            config = analyst_settings()
        except ValueError as error:
            self.agent_busy = False
            self.analyst_panel.begin(road_id, 'configuration error')
            self.analyst_panel.set_status(str(error), error=True)
            return 'break'
        self.analyst_panel.begin(road_id, config['model'], config['history_model'])
        network, factory, events = self.network, self.agent_factory, self.agent_events

        def emit(kind, value):
            if not cancel.is_set():
                events.put((generation, kind, value))

        def run():
            try:
                factory(config).analyze(network, road_id, cancel, emit)
            except CancelledError:
                pass
            except Exception as error:
                # Only controlled errors reach the UI; never display provider URLs/keys.
                message = str(error) if isinstance(error, ValueError) else 'Analysis failed. Check traffic configuration and Ollama, then retry.'
                emit('error', message)
            finally:
                emit('finished', None)

        self.agent_thread = Thread(target=run, daemon=True, name='traffic-analysts')
        self.agent_thread.start()
        return 'break'

    def focus_analyzed_road(self):
        if self.closed or not self.agent_target or not self.network:
            return
        coordinate, _ = sample_road(self.network.roads_by_id[self.agent_target])
        point = project(*coordinate)
        panel_right = self.details.winfo_x() + self.details.winfo_width() + 12
        x = (min(panel_right, self.camera.width - 40) + self.camera.width) / 2
        self.camera = replace(self.camera, x=point[0] - (x - self.camera.width / 2) / self.camera.scale,
                              y=point[1])
        self.invalidate()

    def close_analyst(self):
        self.agent_cancel.set()
        self.agent_generation += 1
        self.agent_busy = False
        self.agent_target = None
        self.analyst_panel.place_forget()
        self.map_area.place_configure(relwidth=1)
        for button in self.controls.winfo_children():
            button.pack_configure(side='left', fill='none')
        self.controls.place_configure(relx=1, rely=0, x=-16, y=16, anchor='ne')
        self.status.place_configure(y=-12)

    def poll_analyst(self):
        tokens = {'live': [], 'historical': []}
        for _ in range(200):
            try:
                generation, kind, value = self.agent_events.get_nowait()
            except Empty:
                break
            if generation != self.agent_generation or not self.agent_target:
                continue
            agent = 'live'
            if kind == 'agent_event':
                agent, kind, value = value['agent'], value['kind'], value['value']
            if kind == 'token':
                tokens[agent].append(value)
            elif kind == 'status':
                self.analyst_panel.set_status(value, agent=agent)
            elif kind == 'evidence':
                self.analyst_panel.set_evidence(value, agent=agent)
            elif kind == 'error':
                self.analyst_panel.set_status(value, error=True, agent=agent)
                tokens[agent].append('\n\n' + value)
            elif kind == 'finished':
                self.agent_busy = False
            elif kind == 'done':
                self.analyst_panel.set_status(value, agent=agent)
        for agent, chunks in tokens.items():
            if chunks:
                self.analyst_panel.append(''.join(chunks), agent=agent)

    def pick(self, x, y):
        if self.network is None:
            return
        node = nearest_node(self.network, self.camera, x, y)
        if node:
            self.select_node(node['id'])
            return
        road = nearest_road(self.network, self.camera, x, y)
        if road:
            self.select_road(road.id)
        else:
            self.clear_selection()

    def hover(self, event):
        if self.network is None or self.drag_origin:
            return
        node = nearest_node(self.network, self.camera, event.x, event.y)
        if node:
            x, y = self.camera.screen(node['point'])
            self.canvas.coords(self.hover_item, x - 5, y - 5, x + 5, y + 5)
            self.canvas.tag_raise(self.hover_item)
            self.canvas.configure(cursor='hand2')
        else:
            self.hide_hover()
            road = nearest_road(self.network, self.camera, event.x, event.y)
            self.canvas.configure(cursor='hand2' if road else 'fleur')

    def hide_hover(self):
        self.canvas.coords(self.hover_item, -100, -100, -90, -90)
        self.canvas.configure(cursor='fleur')

    def invalidate(self):
        self.render_generation += 1
        self.dirty = True
        self.hide_hover()

    def resize(self, event):
        if event.width > 0 and event.height > 0:
            if not hasattr(self, 'detail_body'):
                return
            self.camera = replace(self.camera, width=event.width, height=event.height)
            scaling = self.details._get_widget_scaling()
            self.detail_body.configure(height=max(150, min(350, event.height / scaling - 260)))
            attribution_width = min(560, max(150, event.width / scaling - 32))
            self.attribution.configure(width=attribution_width, height=48,
                                       wraplength=attribution_width)
            self.invalidate()

    def reset_camera(self):
        self.camera = replace(self.camera, x=CENTRE[0], y=CENTRE[1], zoom=11)
        self.invalidate()
        self.update_zoom_buttons()

    def update_zoom_buttons(self):
        self.zoom_in_button.configure(state='disabled' if self.camera.zoom == 18 else 'normal')
        self.zoom_out_button.configure(state='disabled' if self.camera.zoom == 8 else 'normal')

    def zoom(self, delta, x=None, y=None):
        old = self.camera
        level = max(8, min(18, old.zoom + delta))
        if level == old.zoom:
            return
        x = old.width / 2 if x is None else x
        y = old.height / 2 if y is None else y
        world = old.world(x, y)
        new = replace(old, zoom=level)
        self.camera = replace(new, x=world[0] - (x - old.width / 2) / new.scale,
                              y=world[1] - (y - old.height / 2) / new.scale)
        self.invalidate()
        self.update_zoom_buttons()

    def pan_keyboard(self, dx, dy):
        self.camera = replace(self.camera, x=self.camera.x + dx / self.camera.scale,
                              y=max(0, min(1, self.camera.y + dy / self.camera.scale)))
        self.invalidate()

    def press(self, event):
        self.canvas.focus_set()
        self.drag_origin = event.x, event.y, self.camera
        self.dragged = False

    def drag(self, event):
        if not self.drag_origin:
            return
        x, y, old = self.drag_origin
        dx, dy = event.x - x, event.y - y
        if not self.dragged and abs(dx) + abs(dy) <= 4:
            return
        self.dragged = True
        self.camera = replace(old, x=old.x - dx / old.scale,
                              y=max(0, min(1, old.y - dy / old.scale)))
        if self.display_camera and self.display_camera.zoom == self.camera.zoom:
            self.canvas.coords(self.base_item,
                               (self.display_camera.x - self.camera.x) * self.camera.scale,
                               (self.display_camera.y - self.camera.y) * self.camera.scale)
        self.paint_after = time.perf_counter() + .1
        self.invalidate()

    def release(self, event):
        if not self.drag_origin:
            return
        if not self.dragged:
            self.pick(event.x, event.y)
        self.drag_origin = None
        self.paint_after = 0
        self.invalidate()

    def retry_tiles(self):
        if self.tiles:
            self.tiles.retry()
        elif self.configuration_error:
            try:
                self.config_values = settings()
                self.tiles = TileCache(self.config_values['tile_url'])
                self.attribution.configure(text=self.config_values['attribution'])
                self.configuration_error = ''
            except ValueError as error:
                self.configuration_error = str(error)
        if self.dataset_error and not self.data_future:
            self.dataset_error = ''
            self.data_future = self.worker.submit(load_network)
        self.render_error = ''
        self.invalidate()

    def tick(self):
        if self.closed:
            return
        now = time.perf_counter()
        self.poll_analyst()
        if self.data_future and self.data_future.done():
            future, self.data_future = self.data_future, None
            try:
                self.network = future.result()
                self.dataset_error = ''
            except Exception as error:
                self.dataset_error = f'Road data unavailable: {error}'
            self.invalidate()
        if self.tiles:
            if self.tiles.poll():
                self.invalidate()
            keys = self.camera.tile_keys()
            self.tiles.request(keys)
        else:
            keys = []
        if self.render_future and self.render_future.done():
            future, self.render_future = self.render_future, None
            try:
                generation, camera, image = future.result()
                if generation == self.render_generation:
                    self.map_image = ImageTk.PhotoImage(image, master=self)
                    self.canvas.itemconfigure(self.base_item, image=self.map_image)
                    self.canvas.coords(self.base_item, 0, 0)
                    self.display_camera = camera
                    self.render_error = ''
            except Exception as error:
                self.render_error = f'Map painting failed: {error}'
        if self.dirty and not self.render_future and now >= self.paint_after:
            self.dirty = False
            generation, camera = self.render_generation, self.camera
            tiles = self.tiles.snapshot(keys) if self.tiles else {}
            network, selection = self.network, self.selection

            def render():
                return generation, camera, paint_explore(camera, tiles, network, selection)

            self.render_future = self.worker.submit(render)
        failed = sum(key in self.tiles.failed for key in keys) if self.tiles else 0
        pending = sum(key not in self.tiles.images for key in keys) if self.tiles else 0
        message = self.configuration_error or self.dataset_error or self.render_error
        if not message:
            if self.data_future:
                message = 'Loading roads...'
            elif failed:
                message = f'Basemap unavailable ({failed} tiles). Roads still selectable / Retry map'
            elif pending:
                message = f'Loading basemap / {pending} tiles remaining'
            else:
                message = f'Bengaluru / zoom {self.camera.zoom} / drag to pan'
        if self.status.cget('text') != message:
            self.status.configure(text=message)
        self.after_id = self.after(33, self.tick)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.agent_cancel.set()
        self.after_cancel(self.after_id)
        if self.tiles:
            self.tiles.close()
        self.worker.shutdown(wait=False, cancel_futures=True)
        self.destroy()
