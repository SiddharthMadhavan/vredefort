"""One Tk event loop owns simulation state, interaction and presentation."""
from concurrent.futures import ThreadPoolExecutor
import ctypes
from dataclasses import replace
import math
import sys
import time
import tkinter as tk
from tkinter import font as tkfont
import webbrowser
import customtkinter as ctk
from PIL import ImageTk
from .config import settings
from .data import ROOT, load_datasets
from .geometry import project, line_distance_squared
from .map_renderer import Camera, FONT_FILE, TileCache, paint_map, paint_cars
from .simulation import Simulation

BG = '#0c1510'
FG = '#abd2ad'
BORDER = '#3d5943'
MODES = ['KML width shading', 'KML road graph', 'OSM road graph']

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
        self.closed, self.datasets, self.simulation = False, None, None
        self.running, self.selected, self.pinned = False, None, False
        self.hover_id, self.drag_origin, self.dragged = None, None, False
        self.render_generation, self.dirty = 0, True
        self.render_future, self.render_camera = None, None
        self.map_image, self.car_image, self.car_hits = None, None, []
        self.car_camera = None
        self.cars_dirty = True
        self.mode, self.width_field = MODES[0], 'RR_WIDTH_P'
        self.last_tick, self.last_vehicle_paint = time.perf_counter(), 0
        self.paint_after, self.frame_ms = 0, 33
        self.camera = Camera(*project(77.5946, 12.9716), 11, 1400, 900)
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='map-paint')
        self.data_future = self.worker.submit(load_datasets)
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
        self.car_item = self.canvas.create_image(0, 0, anchor='nw')
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
        self.legend = ctk.CTkLabel(self.panel, text='GRAY: NARROW / DARK GREEN: WIDE\nWidth units unspecified in KML', font=self.small_font, text_color='#819487', justify='left')
        self.legend.pack(anchor='w', padx=15, pady=(2, 8))
        self.roads_var, self.hospitals_var, self.fire_var = tk.BooleanVar(value=True), tk.BooleanVar(value=True), tk.BooleanVar(value=True)
        for text, variable in [('Roads + hover nodes', self.roads_var), ('+ Hospitals', self.hospitals_var), ('F Fire stations', self.fire_var)]:
            ctk.CTkCheckBox(self.panel, text=text, variable=variable, command=self.invalidate, font=self.font, text_color=FG, checkbox_width=16, checkbox_height=16, corner_radius=1, fg_color='#527c5a', border_color=BORDER).pack(anchor='w', padx=15, pady=6)
        self.facility_summary = ctk.CTkLabel(self.panel, text='Loading local datasets...', font=self.small_font, text_color='#819487', justify='left', wraplength=240)
        self.facility_summary.pack(anchor='w', padx=15, pady=(4, 10))
        self.button(self.panel, 'Show all roads', self.show_all, width=242).pack(padx=15, pady=4)
        ctk.CTkLabel(self.panel, text='VEHICLES / PYTHON', font=self.font, text_color='#7eaf87').pack(anchor='w', padx=15, pady=(12, 4))
        entry_row = ctk.CTkFrame(self.panel, fg_color='transparent')
        entry_row.pack(padx=15, pady=3)
        self.count_entry = ctk.CTkEntry(entry_row, width=82, font=self.font, fg_color='#15221a', border_color=BORDER, corner_radius=1)
        self.count_entry.insert(0, '5')
        self.count_entry.pack(side='left')
        ctk.CTkLabel(entry_row, text='cars (1–10,000)', font=self.small_font, text_color=FG).pack(side='left', padx=(8, 0))
        speed_row = ctk.CTkFrame(self.panel, fg_color='transparent')
        speed_row.pack(padx=15, pady=3)
        self.speed_entry = ctk.CTkEntry(speed_row, width=82, font=self.font, fg_color='#15221a', border_color=BORDER, corner_radius=1)
        self.speed_entry.insert(0, '100')
        self.speed_entry.pack(side='left')
        ctk.CTkLabel(speed_row, text='metres / second', font=self.small_font, text_color=FG).pack(side='left', padx=(8, 0))
        self.speed_mps = 100.0
        self.initialize_button = self.button(self.panel, 'Initialize cars', self.initialize_cars, width=242, state='disabled')
        self.initialize_button.pack(padx=15, pady=(6, 4))
        self.play_button = self.button(self.panel, 'Play', self.toggle_simulation, width=242, state='disabled')
        self.play_button.pack(padx=15, pady=4)
        self.button(self.panel, 'Focus cars', self.focus_cars, width=242).pack(padx=15, pady=4)
        self.sim_status = ctk.CTkLabel(self.panel, text='Waiting for road graph...', font=self.small_font, text_color='#819487', wraplength=240, justify='left')
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
        self.button(self.details, 'Close / show all', self.show_all, width=288).pack(padx=16, pady=(6, 12))
        self.reference_url = ''

    def invalidate(self):
        self.render_generation += 1
        self.dirty = True
        self.cars_dirty = True
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
        self.field_select.configure(state='normal' if mode == MODES[0] else 'disabled')
        self.legend.configure(text='GRAY: NARROW / DARK GREEN: WIDE\nWidth units unspecified in KML' if mode == MODES[0] else 'Road graph / hover for node details')
        self.show_all()

    def set_width_field(self, field):
        self.width_field = field
        self.show_all()

    def retry_tiles(self):
        if self.tiles:
            self.tiles.retry()
        self.invalidate()

    def initialize_cars(self):
        if not self.simulation:
            return
        try:
            count = int(self.count_entry.get())
            speed = float(self.speed_entry.get())
            if not math.isfinite(speed) or speed < 0:
                raise ValueError('Speed must be nonnegative and finite')
            self.simulation.initialize_cars(count)
            self.speed_mps = speed
            self.running = False
            self.play_button.configure(text='Play', state='normal')
            self.sim_status.configure(text=f'{count} cars initialized / paused\nStops at edge ends; no routing yet')
            self.last_vehicle_paint = 0
            self.cars_dirty = True
        except ValueError as error:
            self.sim_status.configure(text=str(error))

    def toggle_simulation(self):
        if not self.simulation:
            return
        try:
            speed = float(self.speed_entry.get())
            if not math.isfinite(speed) or speed < 0:
                raise ValueError('Speed must be finite and nonnegative')
            self.speed_mps = speed
        except ValueError as error:
            self.sim_status.configure(text=str(error))
            return
        self.running = not self.running
        self.last_tick = time.perf_counter()
        self.play_button.configure(text='Pause' if self.running else 'Play')
        self.sim_status.configure(text=f'{len(self.simulation.vehicles)} cars / {"running" if self.running else "paused"}\nSpeed: {self.speed_mps:g} m/s')

    def focus_cars(self):
        if not self.simulation or not self.simulation.vehicles:
            return
        positions = [project(*vehicle.position()[0]) for vehicle in self.simulation.vehicles]
        xs, ys = zip(*positions)
        dx, dy = max(xs) - min(xs), max(ys) - min(ys)
        usable_w, usable_h = max(100, self.camera.width - 600), max(100, self.camera.height - 200)
        scale = min(usable_w / max(dx, 1e-8), usable_h / max(dy, 1e-8))
        zoom = max(8, min(13, math.floor(math.log2(scale / 256))))
        self.camera = replace(self.camera, x=(min(xs) + max(xs)) / 2, y=(min(ys) + max(ys)) / 2, zoom=zoom)
        self.invalidate()

    def show_details(self, title, rows, note='', link=''):
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
        if self.selected and self.mode != MODES[0]:
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
        if self.simulation and self.car_camera != self.camera:
            # Camera input can arrive before the next paint tick. Never hit-test stale
            # screen coordinates from the previous viewport.
            self.car_hits = [(*self.camera.screen(project(*vehicle.position()[0])), vehicle) for vehicle in self.simulation.vehicles]
            self.car_camera = self.camera
        car = min(self.car_hits, key=lambda item: (item[0] - x) ** 2 + (item[1] - y) ** 2, default=None)
        if car and (car[0] - x) ** 2 + (car[1] - y) ** 2 <= 225:
            vehicle = car[2]
            self.pinned = True
            self.show_details(vehicle.id.replace('_', ' '), [('Edge', vehicle.edge['id']), ('Start', vehicle.edge['source']), ('End', vehicle.edge['target']), ('Distance', f'{vehicle.distance_m:.1f} m'), ('Edge length', f'{vehicle.edge["length_m"]:.1f} m')], 'Python simulation state. Cars stop at the end of their current edge.')
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
                if self.selected and candidate.id != self.selected:
                    continue
                squared = min(line_distance_squared(x, y, [self.camera.screen(point) for point in path]) for path in candidate.paths)
                if squared <= distance:
                    road, distance = candidate, squared
            if road:
                self.selected, self.pinned = road.id, True
                p = road.properties
                rows = [('ID', road.id)]
                if self.mode == MODES[0]:
                    rows += [('RR_WIDTH_P', p.get('RR_WIDTH_P')), ('RR_width_B', p.get('RR_width_B'))]
                    note = 'Original KML road. Width units are unspecified.'
                else:
                    rows += [('Length', f'{p["length_m"]:.1f} m'), ('Start node', p['source']), ('End node', p['target'])]
                    note = 'One graph edge between its endpoint nodes. Press Escape to show all roads.'
                self.show_details('Road width' if self.mode == MODES[0] else 'Road edge', rows, note)
                self.invalidate()
                return
        self.show_all()

    def show_all(self):
        self.selected, self.pinned = None, False
        self.hide_hover()
        self.details.place_forget()
        self.invalidate()

    def tick(self):
        if self.closed:
            return
        now = time.perf_counter()
        dt = now - self.last_tick
        self.last_tick = now
        if self.data_future and self.data_future.done():
            future, self.data_future = self.data_future, None
            try:
                self.datasets = future.result()
                self.simulation = Simulation(self.datasets['graph'])
                self.initialize_button.configure(state='normal')
                self.initialize_cars()
                h = self.datasets['hospital_metadata']
                self.facility_summary.configure(text=f'{len(self.datasets["hospitals"])} hospitals / {len(self.datasets["fire"])} fire stations\n{h["unresolvedCount"]} hospital records need review')
                self.invalidate()
            except Exception as error:
                self.status.configure(text=f'Dataset loading failed: {error}')
                self.facility_summary.configure(text='Local data could not load. Check data/ and restart.')
        if self.running and self.simulation:
            # Pause while minimized; cap long stalls so resuming cannot teleport cars.
            # Constant-speed motion needs just one backend call per screen tick.
            if self.state() != 'iconic':
                self.simulation.get_next_state(min(dt, .25), self.speed_mps)
                stopped = sum(vehicle.stopped for vehicle in self.simulation.vehicles)
                self.sim_status.configure(text=f'{len(self.simulation.vehicles)} cars / {self.simulation.elapsed_s:.1f}s\n{stopped} stopped at edge ends')
                self.cars_dirty = True
                if stopped == len(self.simulation.vehicles):
                    self.running = False
                    self.play_button.configure(text='Play')
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
                generation, image = future.result()
                if generation == self.render_generation:
                    self.map_image = ImageTk.PhotoImage(image, master=self)
                    self.canvas.itemconfigure(self.base_item, image=self.map_image)
                    self.canvas.coords(self.base_item, 0, 0)
            except Exception as error:
                self.status.configure(text=f'Map painting failed: {error}')
        if self.datasets and self.dirty and not self.render_future and now >= self.paint_after:
            self.dirty = False
            generation, camera = self.render_generation, self.camera
            arguments = (camera, self.tiles.snapshot(keys) if self.tiles else {}, self.datasets, self.mode, self.width_field, self.roads_var.get(), self.hospitals_var.get(), self.fire_var.get(), self.selected)
            def render():
                return generation, paint_map(*arguments)
            self.render_future = self.worker.submit(render)
        if self.simulation and (self.running or self.cars_dirty):
            image, self.car_hits = paint_cars(self.camera, self.simulation.vehicles)
            self.car_camera = self.camera
            self.car_image = ImageTk.PhotoImage(image, master=self)
            self.canvas.itemconfigure(self.car_item, image=self.car_image)
            self.canvas.coords(self.car_item, 0, 0)
            self.last_vehicle_paint = now
            self.cars_dirty = False
        if self.datasets:
            failed = sum(key in self.tiles.failed for key in keys) if self.tiles else 0
            pending = sum(key not in self.tiles.images for key in keys) if self.tiles else 0
            message = self.configuration_error or (f'Basemap unavailable ({failed} tiles); local layers still work / Retry tiles' if failed else f'Loading basemap / {pending} tiles remaining' if pending else f'Bengaluru / zoom {self.camera.zoom} / drag to pan, wheel to zoom')
            self.status.configure(text=message)
        self.after_id = self.after(self.frame_ms, self.tick)

    def close(self):
        self.closed = True
        self.after_cancel(self.after_id)
        if self.tiles:
            self.tiles.close()
        self.worker.shutdown(wait=False, cancel_futures=True)
        self.destroy()
