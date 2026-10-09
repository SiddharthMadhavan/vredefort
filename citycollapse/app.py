"""One Tk event loop owns simulation state, interaction and presentation."""
from concurrent.futures import ThreadPoolExecutor, CancelledError
import ctypes
from dataclasses import replace
import sys
import time
from threading import Event
import tkinter as tk
from tkinter import font as tkfont
import webbrowser
import customtkinter as ctk
from PIL import Image, ImageTk
from .config import settings
from .data import DATA, load_datasets
from .geometry import project, line_distance_squared
from .map_renderer import Camera, FONT_FILE, TileCache, paint_map, TrafficPainter
from .traffic import TrafficDataset, TrafficModel
from .traffic_animation import FlowLayer

BG = '#0c1510'
FG = '#abd2ad'
BORDER = '#3d5943'
MODES = ['Traffic simulation', 'KML width shading', 'KML road graph', 'OSM road graph']


def load_application_data():
    datasets = load_datasets()
    try:
        model = TrafficModel(datasets['graph'], TrafficDataset.load(DATA))
        return datasets, model, ''
    except (OSError, ValueError, KeyError) as error:
        return datasets, None, str(error)

class CityCollapseApp(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode('dark')
        ctk.set_default_color_theme('green')
        if sys.platform == 'win32' and FONT_FILE.exists():
            ctypes.windll.gdi32.AddFontResourceExW(str(FONT_FILE), 0x10, 0)
        super().__init__()
        self.title('CityCollapse / Bengaluru')
        scale = self._get_window_scaling()
        width = min(1400, int((self.winfo_screenwidth() - 80) / scale))
        height = min(900, int((self.winfo_screenheight() - 140) / scale))
        self.geometry(f'{width}x{height}+40+30')
        self.minsize(880, 620)
        self.configure(fg_color='#0b100d')
        self.font_name = 'VT323' if 'VT323' in tkfont.families(self) else 'Courier New'
        self.font = ctk.CTkFont(self.font_name, 20)
        self.small_font = ctk.CTkFont(self.font_name, 17)
        self.closed, self.datasets, self.traffic_model = False, None, None
        self.running, self.selected, self.pinned = False, None, False
        self.hover_id, self.drag_origin, self.dragged = None, None, False
        self.render_generation, self.dirty = 0, True
        self.render_future, self.render_camera = None, None
        self.map_image, self.traffic_image = None, None
        self.traffic_result, self.traffic_future, self.traffic_paint_future = None, None, None
        self.traffic_cancel_event = None
        self.requested_key, self.result_key, self.failed_key = None, None, None
        self.blocked_edges, self.blocked_nodes = set(), set()
        self.action_target = None
        self.clock_s, self.playback_speed = 0.0, 60.0
        self.traffic_revision = 0
        self.traffic_painted_revision = -1
        self.traffic_painter = TrafficPainter()
        self.traffic_display_bitmap, self.traffic_bitmap_camera = None, None
        self.traffic_fade_from, self.traffic_fade_to = None, None
        self.traffic_fade_started = 0.0
        self.flow_elapsed_s = 0.0
        self.render_error, self.traffic_render_error = '', ''
        self.mode, self.width_field = MODES[0], 'RR_WIDTH_P'
        self.last_tick = time.perf_counter()
        self.paint_after, self.frame_ms = 0, 16
        self.camera = Camera(*project(77.5946, 12.9716), 11, 1400, 900)
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='map-paint')
        self.data_future = self.worker.submit(load_application_data)
        self.tiles = None
        try:
            self.config_values = settings()
            self.tiles = TileCache(self.config_values['tile_url'])
            self.configuration_error = ''
        except ValueError as error:
            self.config_values = {'attribution': '© OpenStreetMap contributors · © CARTO | Hospital matches: OSM / ODbL'}
            self.configuration_error = str(error)
        self._build_widgets()
        self.bind('<Escape>', lambda event: self.show_all())
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after_id = self.after(33, self.tick)

    def button(self, parent, text, command, **kwargs):
        return ctk.CTkButton(parent, text=text, command=command, font=self.font, text_color=FG, fg_color='#15251a', hover_color='#233d29', border_width=1, border_color=BORDER, corner_radius=2, height=32, **kwargs)

    def _build_widgets(self):
        self.canvas = tk.Canvas(self, background='#0b100d', highlightthickness=0, cursor='fleur')
        self.canvas.pack(fill='both', expand=True)
        self.base_item = self.canvas.create_image(0, 0, anchor='nw')
        self.traffic_item = self.canvas.create_image(0, 0, anchor='nw')
        self.flow_layer = FlowLayer(self.canvas)
        self.hover_item = self.canvas.create_rectangle(-100, -100, -90, -90, fill='#70b67a', outline='#c4e5c4', width=2)
        self.canvas.bind('<Configure>', self.resize)
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.canvas.bind('<Motion>', self.hover)
        self.canvas.bind('<Leave>', lambda event: self.hide_hover())
        self.canvas.bind('<MouseWheel>', lambda event: self.zoom(1 if event.delta > 0 else -1, event.x, event.y))
        self.canvas.bind('<Button-4>', lambda event: self.zoom(1, event.x, event.y))
        self.canvas.bind('<Button-5>', lambda event: self.zoom(-1, event.x, event.y))
        self.canvas.bind('<Key-plus>', lambda event: self.zoom(1))
        self.canvas.bind('<Key-minus>', lambda event: self.zoom(-1))
        for key, dx, dy in [('Left', -100, 0), ('Right', 100, 0), ('Up', 0, -100), ('Down', 0, 100)]:
            self.canvas.bind(f'<{key}>', lambda event, dx=dx, dy=dy: self.pan_keyboard(dx, dy))
        self.panel = ctk.CTkScrollableFrame(self, width=252, height=650, fg_color=BG, corner_radius=2, border_width=1, border_color=BORDER, scrollbar_button_color=BORDER, scrollbar_button_hover_color='#567d60')
        self.panel.place(x=16, y=16)
        ctk.CTkLabel(self.panel, text='CITYCOLLAPSE_', font=ctk.CTkFont(self.font_name, 29), text_color=FG).pack(anchor='w', padx=15, pady=(10, 0))
        ctk.CTkLabel(self.panel, text='BENGALURU / EXPLORE', font=self.small_font, text_color='#7eaf87').pack(anchor='w', padx=15, pady=(0, 10))
        self.mode_select = ctk.CTkOptionMenu(self.panel, values=MODES, command=self.set_mode, font=self.font, dropdown_font=self.font, fg_color='#15221a', button_color=BORDER, button_hover_color='#567d60', text_color=FG, width=242, corner_radius=1)
        self.mode_select.pack(padx=15, pady=4)
        self.field_select = ctk.CTkOptionMenu(self.panel, values=['RR_WIDTH_P', 'RR_width_B'], command=self.set_width_field, font=self.font, dropdown_font=self.font, fg_color='#15221a', button_color=BORDER, text_color=FG, width=242, corner_radius=1)
        self.field_select.pack(padx=15, pady=4)
        self.field_select.configure(state='disabled')
        self.legend = ctk.CTkLabel(self.panel, text='GREEN: LOW / RED: HIGH\nLight trails flow along the roads', font=self.small_font, text_color='#819487', justify='left', wraplength=240)
        self.legend.pack(anchor='w', padx=15, pady=(2, 8))
        self.field_select.pack_forget()
        self.traffic_controls = ctk.CTkFrame(self.panel, fg_color='transparent')
        self.traffic_controls.pack(fill='x')
        self.layer_controls = ctk.CTkFrame(self.panel, fg_color='transparent')
        self.layer_controls.pack(fill='x', pady=(10, 0))
        self.roads_var, self.hospitals_var, self.fire_var = tk.BooleanVar(value=True), tk.BooleanVar(value=True), tk.BooleanVar(value=True)
        for text, variable in [('Roads + hover nodes', self.roads_var), ('+ Hospitals', self.hospitals_var), ('F Fire stations', self.fire_var)]:
            ctk.CTkCheckBox(self.layer_controls, text=text, variable=variable, command=self.invalidate, font=self.font, text_color=FG, checkbox_width=16, checkbox_height=16, corner_radius=1, fg_color='#527c5a', border_color=BORDER).pack(anchor='w', padx=15, pady=6)
        self.facility_summary = ctk.CTkLabel(self.layer_controls, text='Loading local datasets...', font=self.small_font, text_color='#819487', justify='left', wraplength=240)
        self.facility_summary.pack(anchor='w', padx=15, pady=(4, 10))
        self.button(self.layer_controls, 'Show all roads', self.show_all, width=242).pack(padx=15, pady=4)
        ctk.CTkLabel(self.traffic_controls, text='SYNTHETIC TRAFFIC / HOURLY', font=self.font, text_color='#7eaf87').pack(anchor='w', padx=15, pady=(4, 4))
        self.time_label = ctk.CTkLabel(self.traffic_controls, text='Loading traffic...', font=self.font, text_color=FG)
        self.time_label.pack(anchor='w', padx=15, pady=4)
        self.hour_slider = ctk.CTkSlider(self.traffic_controls, from_=0, to=167, number_of_steps=167, command=self.seek_hour, width=242, button_color='#83b98b', progress_color='#527c5a', state='disabled')
        self.hour_slider.set(0)
        self.hour_slider.pack(padx=15, pady=6)
        hour_row = ctk.CTkFrame(self.traffic_controls, fg_color='transparent')
        hour_row.pack(padx=15, pady=4)
        self.previous_button = self.button(hour_row, '< Hour', lambda: self.step_hour(-1), width=116, state='disabled')
        self.previous_button.pack(side='left', padx=(0, 6))
        self.next_button = self.button(hour_row, 'Hour >', lambda: self.step_hour(1), width=116, state='disabled')
        self.next_button.pack(side='left')
        self.speed_select = ctk.CTkOptionMenu(self.traffic_controls, values=['60x', '300x', '900x', '3600x'], command=self.set_playback_speed, font=self.font, dropdown_font=self.font, width=242, fg_color='#15221a', button_color=BORDER, text_color=FG, corner_radius=1)
        self.speed_select.pack(padx=15, pady=4)
        self.play_button = self.button(self.traffic_controls, 'Play', self.toggle_simulation, width=242, state='disabled')
        self.play_button.pack(padx=15, pady=4)
        self.flow_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(self.traffic_controls, text='Animate traffic flow', variable=self.flow_var, command=self.toggle_flow, font=self.font, text_color=FG, checkbox_width=16, checkbox_height=16, corner_radius=1, fg_color='#527c5a', border_color=BORDER).pack(anchor='w', padx=15, pady=6)
        self.closure_summary = ctk.CTkLabel(self.traffic_controls, text='0 roads / 0 junctions blocked', font=self.small_font, text_color='#e1b28b', wraplength=240, justify='left')
        self.closure_summary.pack(anchor='w', padx=15, pady=4)
        self.button(self.traffic_controls, 'Clear all blocks', self.clear_blocks, width=242).pack(padx=15, pady=4)
        self.button(self.traffic_controls, 'Model + assumptions', self.show_model, width=242).pack(padx=15, pady=4)
        self.sim_status = ctk.CTkLabel(self.traffic_controls, text='Loading synthetic traffic...', font=self.small_font, text_color='#819487', wraplength=240, justify='left')
        self.sim_status.pack(anchor='w', padx=15, pady=(4, 10))
        controls = ctk.CTkFrame(self, fg_color=BG, corner_radius=2, border_width=1, border_color=BORDER)
        controls.place(relx=1, x=-16, y=16, anchor='ne')
        for text, command in [('+', lambda: self.zoom(1)), ('−', lambda: self.zoom(-1)), ('Bengaluru', self.reset_camera), ('Panels', self.toggle_panel), ('Retry tiles', self.retry_tiles)]:
            self.button(controls, text, command, width=76).pack(side='left', padx=3, pady=5)
        self.status = ctk.CTkLabel(self, text='Loading local datasets...', font=self.small_font, fg_color=BG, text_color='#9bbca1', corner_radius=2)
        self.status.place(x=16, rely=1, y=-12, anchor='sw')
        self.attribution = ctk.CTkLabel(self, text=self.config_values['attribution'], font=ctk.CTkFont(self.font_name, 15), fg_color=BG, text_color='#819487', cursor='hand2')
        self.attribution.place(relx=1, rely=1, x=-16, y=-12, anchor='se')
        self.attribution.bind('<Button-1>', lambda event: webbrowser.open('https://www.openstreetmap.org/copyright'))
        self.details = ctk.CTkFrame(self, width=324, fg_color=BG, corner_radius=2, border_width=1, border_color=BORDER)
        self.detail_title = ctk.CTkLabel(self.details, text='', font=ctk.CTkFont(self.font_name, 25), text_color=FG, wraplength=288, justify='left')
        self.detail_title.pack(anchor='w', padx=16, pady=(12, 5))
        self.detail_body = ctk.CTkLabel(self.details, text='', font=self.small_font, text_color=FG, wraplength=288, justify='left')
        self.detail_body.pack(anchor='w', padx=16, pady=5)
        self.detail_link = self.button(self.details, 'Hospital search reference ↗', self.open_reference, width=288)
        self.block_button = self.button(self.details, 'Block road', self.toggle_block_target, width=288)
        self.button(self.details, 'Close / show all', self.show_all, width=288).pack(padx=16, pady=(6, 12))
        self.reference_url = ''

    def invalidate(self, traffic=True):
        self.render_generation += 1
        self.dirty = True
        if traffic:
            self.refresh_traffic_layer()
        if not self.roads_var.get():
            self.hide_hover()

    def resize(self, event):
        if event.width > 0 and event.height > 0:
            self.camera = replace(self.camera, width=event.width, height=event.height)
            self.panel.configure(height=max(250, (event.height - 100) / self.panel._get_widget_scaling()))
            self.invalidate()

    def reset_camera(self):
        self.camera = replace(self.camera, x=project(77.5946, 12.9716)[0], y=project(77.5946, 12.9716)[1], zoom=11)
        self.invalidate()

    def zoom(self, delta, x=None, y=None):
        old = self.camera
        x, y = (old.width / 2 if x is None else x), (old.height / 2 if y is None else y)
        zoom = max(8, min(18, old.zoom + delta))
        world = old.world(x, y)
        new = replace(old, zoom=zoom)
        self.camera = replace(new, x=world[0] - (x - old.width / 2) / new.scale, y=world[1] - (y - old.height / 2) / new.scale)
        self.hide_hover()
        self.invalidate()

    def press(self, event):
        self.canvas.focus_set()
        self.drag_origin = event.x, event.y, self.camera
        self.dragged = False

    def pan_keyboard(self, dx, dy):
        self.camera = replace(self.camera, x=self.camera.x + dx / self.camera.scale, y=max(0, min(1, self.camera.y + dy / self.camera.scale)))
        self.hide_hover()
        self.invalidate()

    def drag(self, event):
        if not self.drag_origin:
            return
        x, y, old = self.drag_origin
        dx, dy = event.x - x, event.y - y
        if abs(dx) + abs(dy) > 4:
            self.dragged = True
        self.camera = replace(old, x=old.x - dx / old.scale, y=max(0, min(1, old.y - dy / old.scale)))
        self.canvas.coords(self.base_item, dx, dy)
        self.canvas.coords(self.traffic_item, dx, dy)
        self.hide_hover()
        self.paint_after = time.perf_counter() + .15
        self.invalidate()

    def release(self, event):
        if not self.dragged:
            self.pick(event.x, event.y)
        self.drag_origin = None
        self.paint_after = 0
        self.invalidate()

    def toggle_panel(self):
        if self.panel.winfo_ismapped():
            self.panel.place_forget()
        else:
            self.panel.place(x=16, y=16)

    def set_mode(self, mode):
        self.mode = mode
        self.mode_select.set(mode)
        self.field_select.configure(state='normal' if mode == 'KML width shading' else 'disabled')
        if mode == 'KML width shading':
            self.field_select.pack(padx=15, pady=4, before=self.legend)
        else:
            self.field_select.pack_forget()
        self.legend.configure(text='GREEN: LOW / RED: HIGH\nLight trails flow along the roads' if mode == 'Traffic simulation' else 'GRAY: NARROW / DARK GREEN: WIDE\nWidth units unspecified in KML' if mode == 'KML width shading' else 'Road graph / hover for node details')
        self.show_all()

    def set_width_field(self, field):
        self.width_field = field
        self.show_all()

    def retry_tiles(self):
        if self.tiles:
            self.tiles.retry()
        self.invalidate()

    def toggle_simulation(self):
        if not self.traffic_model:
            return
        if self.clock_s >= len(self.traffic_model.dataset.hours) * 3600:
            self.seek_hour(0)
        self.running = not self.running
        self.last_tick = time.perf_counter()
        self.play_button.configure(text='Pause' if self.running else 'Play')

    def set_playback_speed(self, value):
        self.playback_speed = float(value.rstrip('x'))

    def seek_hour(self, value):
        if self.traffic_model:
            hour = max(0, min(len(self.traffic_model.dataset.hours) - 1, round(float(value))))
            self.clock_s = hour * 3600.0
            self.hour_slider.set(hour)
            self.request_traffic()

    def step_hour(self, delta):
        self.seek_hour(int(self.clock_s // 3600) + delta)

    def refresh_traffic_layer(self):
        self.traffic_revision += 1

    def toggle_flow(self):
        self.flow_layer.dirty = True

    def request_traffic(self):
        if not self.traffic_model:
            return
        hour = min(int(self.clock_s // 3600), len(self.traffic_model.dataset.hours) - 1)
        key = (hour, frozenset(self.blocked_edges), frozenset(self.blocked_nodes))
        if key == self.requested_key:
            return
        self.time_label.configure(text=self.traffic_model.dataset.hours[hour][:16])
        self.hour_slider.set(hour)
        if key != self.requested_key:
            if self.traffic_cancel_event:
                self.traffic_cancel_event.set()
            self.requested_key = key
            # Keep the current image and motion alive until its replacement is ready.
            # New closures stop their trails immediately, even during calculation.
            closed = {edge['id'] for edge in self.traffic_model.edges
                      if edge['id'] in self.blocked_edges or edge['source'] in self.blocked_nodes or edge['target'] in self.blocked_nodes}
            self.flow_layer.set_blocked(closed)
            if key == self.result_key:
                self.update_traffic_summary()
            else:
                self.sim_status.configure(text='Updating synthetic traffic...\nPrevious display remains visible.\nPlayback clock waits for assignment.')
        self.closure_summary.configure(text=f'{len(self.blocked_edges)} roads / {len(self.blocked_nodes)} junctions blocked\nClick a road or junction for block controls')

    def display_traffic_bitmap(self, bitmap):
        self.traffic_display_bitmap = bitmap
        self.traffic_image = ImageTk.PhotoImage(bitmap, master=self)
        self.canvas.itemconfigure(self.traffic_item, image=self.traffic_image)
        self.canvas.coords(self.traffic_item, 0, 0)

    def accept_traffic_frame(self, camera, bitmap, paths, now):
        if self.traffic_bitmap_camera == camera and self.traffic_display_bitmap is not None:
            self.traffic_fade_from = self.traffic_display_bitmap
            self.traffic_fade_to, self.traffic_fade_started = bitmap, now
        else:
            # Crossfading two different viewports produces misaligned roads.
            self.traffic_fade_from = self.traffic_fade_to = None
            self.display_traffic_bitmap(bitmap)
        self.traffic_bitmap_camera = camera
        self.flow_layer.install(camera, paths, self.flow_elapsed_s)
        self.canvas.tag_raise(self.hover_item)

    def update_traffic_fade(self, now):
        if self.traffic_fade_to is None or self.traffic_bitmap_camera != self.camera:
            return
        progress = min(1.0, max(0.0, (now - self.traffic_fade_started) / .65))
        # Smoothstep avoids a sudden start or stop to color/intensity changes.
        eased = progress * progress * (3 - 2 * progress)
        bitmap = self.traffic_fade_to if progress == 1 else Image.blend(self.traffic_fade_from, self.traffic_fade_to, eased)
        self.display_traffic_bitmap(bitmap)
        if progress == 1:
            self.traffic_fade_from = self.traffic_fade_to = None

    def clear_blocks(self):
        self.blocked_edges.clear()
        self.blocked_nodes.clear()
        self.failed_key = None
        self.request_traffic()
        self.show_all()

    def set_action(self, kind, identifier):
        self.action_target = (kind, identifier)
        blocked = identifier in (self.blocked_edges if kind == 'edge' else self.blocked_nodes)
        self.block_button.configure(text=f'{"Unblock" if blocked else "Block"} {"road" if kind == "edge" else "junction"}')
        self.block_button.pack(padx=16, pady=5, before=self.details.winfo_children()[-1])

    def toggle_block_target(self):
        if not self.action_target or not self.traffic_model:
            return
        kind, identifier = self.action_target
        group = self.blocked_edges if kind == 'edge' else self.blocked_nodes
        if identifier in group:
            group.remove(identifier)
        else:
            group.add(identifier)
        self.failed_key = None
        self.request_traffic()
        self.set_action(kind, identifier)

    def show_model(self):
        self.pinned = True
        self.show_details('Synthetic traffic model', [],
            'Hourly replay + conditional incident assignment.\n\n'
            't(q) = t_obs * (1 + .15(q/C)^4) / (1 + .15(b/C)^4)\n\n'
            'C: median flow/utilization from uncapped hours. Detours: shortest time + MSA (1% gap / 60 steps).\n\n'
            'Road trips retain endpoints. Junction turns: min(b_i,b_j)/(k-1). No path: unmet demand.\n\n'
            'Assumed veh/h and km/h. No measured OD, signals, queues or spillback.\n\n'
            'Full math: data/traffic-model.txt')

    def show_details(self, title, rows, note='', link=''):
        self.action_target = None
        self.block_button.pack_forget()
        self.detail_title.configure(text=str(title))
        self.detail_body.configure(text='\n'.join(f'{label}: {value if value not in (None, "") else "Not provided"}' for label, value in rows) + ('\n\n' + note if note else ''))
        self.reference_url = link
        if link:
            self.detail_link.pack(padx=16, pady=5, before=self.details.winfo_children()[-1])
        else:
            self.detail_link.pack_forget()
        self.details.place(relx=1, x=-16, y=78, anchor='ne')

    def open_reference(self):
        from urllib.parse import urlsplit
        url = urlsplit(self.reference_url)
        if url.scheme == 'https' and url.hostname == 'www.google.com' and url.path == '/search':
            webbrowser.open(self.reference_url)

    def hide_hover(self):
        self.canvas.coords(self.hover_item, -100, -100, -90, -90)
        self.hover_id = None
        if not self.pinned:
            self.details.place_forget()

    def node_at(self, x, y):
        if not self.datasets or not self.roads_var.get():
            return None
        view = self.datasets['views'][self.mode]
        box = (*self.camera.world(x - 12, y - 12), *self.camera.world(x + 12, y + 12))
        allowed = None
        if self.selected and self.mode not in ('KML width shading', 'Traffic simulation'):
            p = view['by_id'][self.selected].properties
            allowed = {p['source'], p['target']}
        nearest, distance = None, 144
        for index in view['node_index'].query(box):
            node = view['nodes'][index]
            if allowed and node['id'] not in allowed:
                continue
            sx, sy = self.camera.screen(node['point'])
            squared = (x - sx) ** 2 + (y - sy) ** 2
            if squared <= distance:
                nearest, distance = node, squared
        return nearest

    def node_details(self, node):
        self.show_details(f'Node {node["number"]}', [('ID', node['id']), ('Kind', node['kind'].replace('_', ' ')), ('Connections', node['degree']), ('Longitude', f'{node["coordinate"][0]:.6f}'), ('Latitude', f'{node["coordinate"][1]:.6f}')], 'Inferred from the selected graph. Click the dot to keep details open.')
        if self.pinned and self.traffic_model and self.mode in ('Traffic simulation', 'KML road graph', 'KML width shading'):
            self.set_action('node', node['id'])

    def hover(self, event):
        if self.drag_origin or self.pinned:
            return
        node = self.node_at(event.x, event.y)
        if not node:
            self.hide_hover()
            return
        x, y = self.camera.screen(node['point'])
        self.canvas.coords(self.hover_item, x - 5, y - 5, x + 5, y + 5)
        self.canvas.tag_raise(self.hover_item)
        if self.hover_id != node['id']:
            self.hover_id = node['id']
            self.node_details(node)

    def pick(self, x, y):
        if not self.datasets:
            return
        for kind, enabled in [('hospitals', self.hospitals_var.get()), ('fire', self.fire_var.get())]:
            if not enabled:
                continue
            for point in self.datasets[kind]:
                sx, sy = self.camera.screen(point['point'])
                if abs(sx - x) <= 12 and abs(sy - y) <= 12:
                    self.pinned = True
                    if kind == 'hospitals':
                        note = 'User-provided coordinates; not independently verified.' if point['match_status'] == 'provided_coordinates' else 'Inferred OSM facility match; requires verification.'
                        self.show_details(point['Name'], [('Type', point.get('Type')), ('Address', point.get('Address')), ('Beds', point.get('Beds')), ('Contact', point.get('Contact'))], note, point.get('search_url', ''))
                    else:
                        self.show_details(point['FIRE_STAName'], [('Station ID', point.get('KGISFIRE_STAID')), ('Ward ID', point.get('KGISWardID')), ('KGIS code', point.get('KGISCode'))], 'Original KML coordinates. Survey date unspecified.')
                    return
        node = self.node_at(x, y)
        if node:
            self.pinned = True
            self.node_details(node)
            return
        if self.roads_var.get():
            view = self.datasets['views'][self.mode]
            box = (*self.camera.world(x - 8, y - 8), *self.camera.world(x + 8, y + 8))
            road, distance = None, 64
            for index in view['index'].query(box):
                candidate = view['roads'][index]
                if self.selected and self.mode != 'Traffic simulation' and candidate.id != self.selected:
                    continue
                squared = min(line_distance_squared(x, y, [self.camera.screen(point) for point in path]) for path in candidate.paths)
                if squared <= distance:
                    road, distance = candidate, squared
            if road:
                self.selected, self.pinned = road.id, True
                p = road.properties
                rows = [('ID', road.id)]
                if self.mode == 'KML width shading':
                    rows += [('RR_WIDTH_P', p.get('RR_WIDTH_P')), ('RR_width_B', p.get('RR_width_B'))]
                    note = 'Original KML road. Width units are unspecified.'
                else:
                    rows += [('Length', f'{p["length_m"]:.1f} m'), ('Start node', p['source']), ('End node', p['target'])]
                    note = 'One graph edge between its endpoint nodes. Press Escape to show all roads.'
                if self.mode == 'Traffic simulation':
                    self.show_traffic_edge(road.id)
                else:
                    self.show_details('Road width' if self.mode == 'KML width shading' else 'Road edge', rows, note)
                if self.traffic_model and self.mode in ('Traffic simulation', 'KML road graph'):
                    self.set_action('edge', road.id)
                self.invalidate()
                return
        self.show_all()

    def show_traffic_edge(self, identifier):
        road = self.datasets['views']['KML road graph']['by_id'][identifier]
        rows = [('ID', identifier), ('Length', f'{road.properties["length_m"]:.1f} m')]
        if self.traffic_result:
            state = self.traffic_result.links[identifier]
            edge = self.traffic_model.edges[self.traffic_model.by_id[identifier]]
            blocked_by_node = edge['source'] in self.blocked_nodes or edge['target'] in self.blocked_nodes
            rows += [('State', 'BLOCKED BY JUNCTION' if blocked_by_node else 'BLOCKED' if state.closed else 'OPEN'),
                     ('Baseline', f'{state.baseline:,.0f} veh/h'), ('Scenario', f'{state.flow:,.0f} veh/h'),
                     ('Added detour flow', f'{max(0, state.flow - state.baseline):,.0f} veh/h'),
                     ('Estimated capacity', f'{state.capacity:,.0f} veh/h'),
                     ('Speed', f'{state.speed:.1f} km/h'), ('Congestion', f'{state.congestion:.0%}')]
        self.show_details('Synthetic road traffic', rows, 'Synthetic hourly input and conditional closure model. Background traffic stays fixed; no physical queues are modelled.')

    def show_all(self):
        self.selected, self.pinned = None, False
        self.action_target = None
        self.hide_hover()
        self.details.place_forget()
        self.invalidate()

    def tick(self):
        if self.closed:
            return
        now = time.perf_counter()
        dt = now - self.last_tick
        self.last_tick = now
        if self.running and self.state() != 'iconic':
            self.flow_elapsed_s += min(dt, .25)
        if self.data_future and self.data_future.done():
            future, self.data_future = self.data_future, None
            try:
                self.datasets, self.traffic_model, traffic_error = future.result()
                if self.traffic_model:
                    hours = len(self.traffic_model.dataset.hours)
                    self.hour_slider.configure(to=max(1, hours - 1), number_of_steps=max(1, hours - 1), state='normal')
                    for button in (self.play_button, self.previous_button, self.next_button):
                        button.configure(state='normal')
                    self.request_traffic()
                else:
                    self.sim_status.configure(text=f'Traffic data unavailable: {traffic_error}\nRun scripts/import-traffic.py with the CSV and restart.')
                h = self.datasets['hospital_metadata']
                self.facility_summary.configure(text=f'{len(self.datasets["hospitals"])} hospitals / {len(self.datasets["fire"])} fire stations\n{h["unresolvedCount"]} hospital records need review')
                self.invalidate()
            except Exception as error:
                self.status.configure(text=f'Dataset loading failed: {error}')
                self.facility_summary.configure(text='Local data could not load. Check data/ and restart.')
        if self.traffic_future and self.traffic_future[1].done():
            key, future = self.traffic_future
            self.traffic_future = None
            try:
                result = future.result()
                if key == self.requested_key:
                    self.traffic_result, self.result_key = result, key
                    self.failed_key = None
                    self.refresh_traffic_layer()
                    self.update_traffic_summary()
                    if self.pinned and self.action_target and self.action_target[0] == 'edge' and self.mode == 'Traffic simulation':
                        target = self.action_target
                        self.show_traffic_edge(target[1])
                        self.set_action(*target)
            except CancelledError:
                pass
            except Exception as error:
                if key == self.requested_key:
                    self.failed_key = key
                    self.running = False
                    self.play_button.configure(text='Play')
                    self.sim_status.configure(text=f'Traffic assignment failed: {error}\nClear blocks or change hour to retry.')
        if self.running and self.traffic_model and self.result_key == self.requested_key and self.traffic_result:
            # Backpressure: hold the clock while the latest scenario is computing.
            if self.state() != 'iconic':
                self.clock_s = min(len(self.traffic_model.dataset.hours) * 3600, self.clock_s + min(dt, .25) * self.playback_speed)
                self.request_traffic()
                if self.clock_s >= len(self.traffic_model.dataset.hours) * 3600:
                    self.running = False
                    self.play_button.configure(text='Replay')
        if self.traffic_model and not self.traffic_future and (not self.traffic_result or self.result_key != self.requested_key) and self.failed_key != self.requested_key:
            key = self.requested_key
            self.traffic_cancel_event = Event()
            self.traffic_future = key, self.worker.submit(self.traffic_model.solve, *key, cancel_event=self.traffic_cancel_event)
        if self.tiles:
            if self.tiles.poll():
                self.invalidate(traffic=False)
            keys = self.camera.tile_keys()
            self.tiles.request(keys)
        else:
            keys = []
        if self.render_future and self.render_future.done():
            future, self.render_future = self.render_future, None
            try:
                generation, image = future.result()
                if generation == self.render_generation:
                    self.map_image = ImageTk.PhotoImage(image, master=self)
                    self.canvas.itemconfigure(self.base_item, image=self.map_image)
                    self.canvas.coords(self.base_item, 0, 0)
                    self.render_error = ''
            except Exception as error:
                self.render_error = f'Map painting failed: {error}'
        if self.datasets and self.dirty and not self.render_future and now >= self.paint_after:
            self.dirty = False
            generation, camera = self.render_generation, self.camera
            arguments = (camera, self.tiles.snapshot(keys) if self.tiles else {}, self.datasets, self.mode, self.width_field, self.roads_var.get(), self.hospitals_var.get(), self.fire_var.get(), None if self.mode == 'Traffic simulation' else self.selected)
            def render(generation=generation, arguments=arguments):
                return generation, paint_map(*arguments)
            self.render_future = self.worker.submit(render)
        if self.traffic_paint_future and self.traffic_paint_future.done():
            future, self.traffic_paint_future = self.traffic_paint_future, None
            try:
                revision, camera, image, paths = future.result()
                if revision == self.traffic_revision and self.mode == 'Traffic simulation' and self.roads_var.get():
                    self.accept_traffic_frame(camera, image, paths, now)
                    self.traffic_painted_revision = revision
                    self.traffic_render_error = ''
            except Exception as error:
                self.traffic_render_error = f'Traffic painting failed: {error}'
        if self.mode != 'Traffic simulation' or not self.roads_var.get() or not self.traffic_result:
            self.canvas.itemconfigure(self.traffic_item, image='')
            self.flow_layer.hide()
        else:
            if not self.traffic_paint_future and self.traffic_painted_revision != self.traffic_revision:
                revision, camera = self.traffic_revision, self.camera
                arguments = (camera, self.datasets['views']['KML road graph'], self.traffic_result, self.selected)
                def paint(revision=revision, camera=camera, arguments=arguments):
                    image, paths = self.traffic_painter.frame(*arguments)
                    return revision, camera, image, paths
                self.traffic_paint_future = self.worker.submit(paint)
            self.update_traffic_fade(now)
            enabled = self.flow_var.get() and not self.drag_origin and self.state() != 'iconic'
            if self.running or self.flow_layer.dirty or enabled != self.flow_layer.enabled or self.camera != self.flow_layer.camera:
                self.flow_layer.draw(self.camera, self.flow_elapsed_s, enabled)
        if self.datasets:
            failed = sum(key in self.tiles.failed for key in keys) if self.tiles else 0
            pending = sum(key not in self.tiles.images for key in keys) if self.tiles else 0
            message = self.configuration_error or self.render_error or self.traffic_render_error or (f'Basemap unavailable ({failed} tiles); local layers still work / Retry tiles' if failed else f'Loading basemap / {pending} tiles remaining' if pending else f'Bengaluru / zoom {self.camera.zoom} / drag to pan, wheel to zoom')
            if self.status.cget('text') != message:
                self.status.configure(text=message)
        self.after_id = self.after(self.frame_ms, self.tick)

    def update_traffic_summary(self):
        r = self.traffic_result
        if not r:
            return
        baseline = 'Baseline / no diversions' if not r.affected_demand else f'Affected: {r.affected_demand:,.0f} veh/h\nRerouted: {r.rerouted_demand:,.0f} veh/h\nUnmet: {r.unmet_demand:,.0f} veh/h'
        solver = '' if not r.iterations else f'\nMSA: {r.iterations} steps / gap {r.relative_gap:.1%}' + (' / approximate' if not r.converged else '')
        self.sim_status.configure(text=f'{len(r.links):,} roads / synthetic inputs\n{baseline}{solver}\nHourly snapshots; no physical queues')

    def close(self):
        self.closed = True
        if self.traffic_cancel_event:
            self.traffic_cancel_event.set()
        self.after_cancel(self.after_id)
        if self.tiles:
            self.tiles.close()
        self.worker.shutdown(wait=False, cancel_futures=True)
        self.destroy()
