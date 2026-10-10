"""Scrollable closure report with complete paginated lists and route previews."""
import customtkinter as ctk


class ImpactPanel(ctk.CTkFrame):
    PAGE_SIZE = 30

    def __init__(self, parent, font, small_font, on_road, on_facility, on_route, on_focus, on_close):
        super().__init__(parent, width=354, fg_color='#0c1510', corner_radius=2,
                         border_width=1, border_color='#3d5943')
        self.font, self.small_font = font, small_font
        self.on_road, self.on_facility, self.on_route = on_road, on_facility, on_route
        self.report, self.result, self.page, self.tab = None, None, 0, 'Roads'
        self.rows = []
        self.maximum_body_height, self.fit_job = 250, None
        header = ctk.CTkFrame(self, fg_color='transparent')
        header.pack(fill='x', padx=12, pady=(8, 0))
        ctk.CTkLabel(header, text='CLOSURE IMPACTS_', font=font, text_color='#abd2ad').pack(side='left')
        self.action_button(header, 'X', on_close, width=32).pack(side='right')
        self.summary = ctk.CTkLabel(self, text='', font=small_font, text_color='#e1b28b', justify='left', wraplength=320)
        self.summary.pack(anchor='w', padx=12, pady=5)
        self.action_button(self, 'Fit all impacts + detours', on_focus, width=320).pack(padx=12, pady=4)
        self.tabs = ctk.CTkSegmentedButton(self, values=['Roads', 'Facilities', 'Diversions'], command=self.set_tab,
                                          font=small_font, text_color='#abd2ad', fg_color='#15251a',
                                          selected_color='#3d5943', selected_hover_color='#567d60',
                                          unselected_color='#15251a', unselected_hover_color='#233d29', corner_radius=1)
        self.tabs.set('Roads')
        self.tabs.pack(fill='x', padx=12, pady=4)
        self.note = ctk.CTkLabel(self, text='', font=small_font, text_color='#819487', wraplength=320, justify='left')
        self.note.pack(anchor='w', padx=12, pady=5)
        self.body = ctk.CTkScrollableFrame(self, width=302, height=250, fg_color='transparent', corner_radius=1,
                                          scrollbar_button_color='#3d5943')
        self.body.pack(fill='both', expand=True, padx=8, pady=4)
        pagination = ctk.CTkFrame(self, fg_color='transparent')
        pagination.pack(fill='x', padx=12, pady=(4, 8))
        self.previous = self.action_button(pagination, '<', lambda: self.turn_page(-1), width=42)
        self.previous.pack(side='left')
        self.page_label = ctk.CTkLabel(pagination, text='', font=small_font, text_color='#819487')
        self.page_label.pack(side='left', expand=True)
        self.next = self.action_button(pagination, '>', lambda: self.turn_page(1), width=42)
        self.next.pack(side='right')

    def action_button(self, parent, text, command, **kwargs):
        return ctk.CTkButton(parent, text=text, command=command, font=self.small_font, text_color='#abd2ad',
                            fg_color='#15251a', hover_color='#233d29', border_width=1, border_color='#3d5943',
                            corner_radius=1, height=30, **kwargs)

    def set_report(self, report, result):
        self.report, self.result = report, result
        self.summary.configure(text=f'{len(report.closed_roads)} blocked / {len(report.loaded_roads)} roads with extra traffic\n'
                                    f'{len(report.affected_nodes)} connected nodes / {len(report.facilities)} nearby facilities\n'
                                    f'Rerouted {result.rerouted_demand:,.0f} / unmet {result.unmet_demand:,.0f} veh/h\n'
                                    'RED: blocked / GOLD: changed / CYAN: detours')
        self.render_page()

    def set_tab(self, value):
        self.tab, self.page = value, 0
        self.tabs.set(value)
        self.render_page()

    def turn_page(self, delta):
        self.page = max(0, self.page + delta)
        self.render_page()

    def resize_body(self, height):
        self.maximum_body_height = max(100, height)
        self.schedule_fit()

    def schedule_fit(self):
        if self.fit_job is None:
            self.fit_job = self.after_idle(self.fit_body)

    def fit_body(self):
        self.fit_job = None
        scale = self._get_widget_scaling()
        overhead = max(0, self.winfo_reqheight() - self.body.cget('height') * scale)
        top = 78 * self.master._get_window_scaling()
        available = (self.master.winfo_height() - top - 24 - overhead) / scale
        height = max(90, min(self.maximum_body_height, available))
        if abs(self.body.cget('height') - height) > .5:
            self.body.configure(height=height)

    def render_page(self):
        if not self.report:
            return
        r = self.report
        if self.tab == 'Roads':
            items = sorted(r.closed_roads) + sorted(r.loaded_roads, key=lambda key: (-(self.result.links[key].flow - self.result.links[key].baseline), key))
            self.note.configure(text='All blocked roads and roads receiving diverted traffic. Click a row for its exact flow change and map location.')
        elif self.tab == 'Facilities':
            items = list(r.facilities)
            self.note.configure(text=f'Within {r.radius_m:g}m of affected roads. Potential access delay; proximity does not establish an outage. Only mapped facilities are included.')
        else:
            items = list(r.diversions) + list(r.unavailable)
            self.note.configure(text='Up to 3 shortest graph paths per blocked road; junction routes show assigned flow. Click to preview. Undirected graph: legal turns and one-way restrictions are unknown; routes need verification.')
        pages = max(1, (len(items) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self.page = min(self.page, pages - 1)
        start = self.page * self.PAGE_SIZE
        displayed = items[start:start + self.PAGE_SIZE]
        while len(self.rows) < max(1, len(displayed)):
            button = self.action_button(self.body, '', lambda: None, width=296)
            label = ctk.CTkLabel(self.body, text='', font=self.small_font, text_color='#e1b28b', justify='left', wraplength=284)
            self.rows.append((button, label))
        for button, label in self.rows:
            button.pack_forget()
            label.pack_forget()
        for row_index, item in enumerate(displayed):
            i = start + row_index + 1
            button, label = self.rows[row_index]
            if self.tab == 'Roads':
                state = self.result.links[item]
                title, command = item, lambda key=item: self.on_road(key)
                text = f'BLOCKED / baseline {state.baseline:,.0f} veh/h' if state.closed else f'{state.baseline:,.0f} -> {state.flow:,.0f} veh/h / +{state.flow - state.baseline:,.1f}\nTravel time +{(state.delay_ratio - 1) * 100:.1f}%'
            elif self.tab == 'Facilities':
                title, command = item.name[:38], lambda facility=item: self.on_facility(facility)
                text = f'{"Hospital" if item.kind == "hospitals" else "Fire station"} / {item.distance_m:.0f}m from affected road\nNear {"closure" if item.near_closed else "diverted traffic"} / {len(item.road_ids)} affected roads'
            elif isinstance(item, tuple):
                title, command = item[0], lambda key=item[0]: self.on_road(key)
                text = item[1]
            else:
                route = item.route
                title, command = f'Preview route {i} / {route.travel_time_s / 60:.1f} min', lambda option=item: self.on_route(option)
                text = f'{route.length_m / 1000:.2f} km / {len(route.edge_ids)} roads\n' + (f'Assigned {route.flow:,.1f} veh/h' if item.assigned else f'Closure: {item.closure_id}')
            button.configure(text=title, command=command)
            button.pack(pady=(4, 0))
            label.configure(text=text)
            label.pack(anchor='w', padx=4, pady=(0, 7))
        if not items:
            label = self.rows[0][1]
            label.configure(text='No items for this scenario.')
            label.pack(pady=12)
        self.page_label.configure(text=f'{start + 1 if items else 0}-{min(start + self.PAGE_SIZE, len(items))} / {len(items)}')
        self.previous.configure(state='normal' if self.page > 0 else 'disabled')
        self.next.configure(state='normal' if self.page + 1 < pages else 'disabled')
        self.body._parent_canvas.yview_moveto(0)
        self.schedule_fit()
