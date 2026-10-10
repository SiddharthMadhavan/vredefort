"""Paginated junction accessibility report using the existing root Tk loop."""
import math
import customtkinter as ctk
from .emergency_services import COLORS, SERVICE_NAMES, STATUS_NAMES


def minutes(seconds):
    return f'{seconds / 60:.1f} min' if math.isfinite(seconds) else 'No mapped path'


class EmergencyPanel(ctk.CTkFrame):
    PAGE_SIZE = 20

    def __init__(self, parent, controller):
        super().__init__(parent, fg_color='#0c1510', corner_radius=0)
        self.controller = controller
        self.report, self.page, self.rows = None, 0, []
        app = controller.sim.app
        self.small_font = app.small_font
        ctk.CTkLabel(self, text='EMERGENCY ACCESS_', font=app.font, text_color='#abd2ad').pack(anchor='w', padx=16, pady=(12, 4))
        actions = ctk.CTkFrame(self, fg_color='transparent')
        actions.pack(fill='x', padx=16, pady=4)
        self.overlay = ctk.CTkCheckBox(actions, text='Show on map', font=app.small_font,
            command=self.toggle_overlay, text_color='#abd2ad', checkbox_width=18, checkbox_height=18)
        self.overlay.pack(side='left')
        self.overlay.select()
        self.kind = ctk.CTkOptionMenu(actions, values=['All services', 'Fire stations', 'Hospital access'],
            command=self.change_kind, font=app.small_font, dropdown_font=app.small_font,
            fg_color='#15251a', button_color='#3d5943', text_color='#abd2ad')
        self.kind.pack(side='right')
        self.summary = ctk.CTkLabel(self, text='Calculating access...', justify='left', anchor='w',
            font=app.small_font, text_color='#abd2ad', wraplength=430)
        self.summary.pack(fill='x', padx=16, pady=5)
        ctk.CTkLabel(self, text='RED: lost access / ORANGE: over 10 min\nGOLD: +3 min delay / PURPLE: existing graph gap\nF: fire station / H: hospital location',
            justify='left', anchor='w', font=app.small_font, text_color='#c6b6a2').pack(fill='x', padx=16, pady=4)
        self.body = ctk.CTkScrollableFrame(self, fg_color='transparent', scrollbar_button_color='#3d5943')
        self.body._scrollbar.configure(height=80)
        self.body.pack(fill='both', expand=True, padx=8, pady=4)
        pagination = ctk.CTkFrame(self, fg_color='transparent')
        pagination.pack(fill='x', padx=16, pady=4)
        self.previous = app.button(pagination, '<', lambda: self.turn(-1), width=36)
        self.previous.pack(side='left')
        self.page_label = ctk.CTkLabel(pagination, text='', font=app.small_font, text_color='#819487')
        self.page_label.pack(side='left', expand=True)
        self.next = app.button(pagination, '>', lambda: self.turn(1), width=36)
        self.next.pack(side='right')
        self.assumptions = ctk.CTkTextbox(self, height=100, font=app.small_font,
            text_color='#819487', fg_color='transparent', wrap='word', corner_radius=0)
        self.assumptions.insert('1.0', 'Road-travel estimates only. 10 min / +3 min are demo thresholds, not response standards. '
            'Hospital locations are access destinations, not verified ambulance bases. '
            'Only supplied mapped facilities are included (some coordinates are inferred). '
            'Undirected roads; dispatch, capacity, legal turns and off-road travel are unknown. '
            'A facility on a blocked access road has no usable entry in that scenario. '
            'Nearby markers are thinned on the map; all flagged junctions are listed above.')
        self.assumptions.configure(state='disabled')
        self.body.pack_forget()
        pagination.pack_forget()
        self.assumptions.pack(side='bottom', fill='x', padx=16, pady=(4, 12))
        pagination.pack(side='bottom', fill='x', padx=16, pady=4)
        self.body.pack(fill='both', expand=True, padx=8, pady=4)

    def toggle_overlay(self):
        self.controller.enabled = bool(self.overlay.get())
        self.controller.update_button()

    def change_kind(self, value):
        self.controller.kind = {'All services': None, 'Fire stations': 'fire', 'Hospital access': 'hospitals'}[value]
        if self.controller.selected_target and self.controller.kind not in (None, self.controller.selected_target[0]):
            self.controller.selected_target = self.controller.route = None
        self.page = 0
        self.render()

    def turn(self, step):
        self.page = max(0, self.page + step)
        self.render()

    def pending(self, text='Updating emergency access...'):
        self.report = None
        self.summary.configure(text=text)
        self.render()

    def set_report(self, report):
        self.report = report
        self.render()

    def render(self):
        for widget in self.rows:
            widget.destroy()
        self.rows.clear()
        if not self.report:
            self.previous.configure(state='disabled')
            self.next.configure(state='disabled')
            self.page_label.configure(text='Waiting for current scenario')
            return
        r, kind = self.report, self.controller.kind
        points = r.risks(kind)
        counts = {status: sum(p.status == status for p in points) for status in ('lost', 'delayed', 'degraded', 'gap')}
        facilities = sum(kind is None or a.kind == kind for a in r.anchors)
        excluded = sum(kind is None or k == kind for k, name in r.skipped)
        self.summary.configure(text=f'{self.controller.sim.model.dataset.hours[r.hour][:16]} / simulation\n'
            f'{len({p.node_id for p in points})} flagged junctions / {len(points)} service flags\n'
            f'{counts["lost"]} lost / {counts["delayed"]} slow / {counts["degraded"]} added delay\n'
            f'{counts["gap"]} existing gaps / {facilities} mapped facilities\n'
            f'{excluded} facilities excluded: no road within 250m')
        pages = max(1, (len(points) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self.page = min(self.page, pages - 1)
        self.previous.configure(state='normal' if self.page else 'disabled')
        self.next.configure(state='normal' if self.page + 1 < pages else 'disabled')
        self.page_label.configure(text=f'{self.page + 1} / {pages} pages')
        for point in points[self.page * self.PAGE_SIZE:(self.page + 1) * self.PAGE_SIZE]:
            added = point.added_seconds
            text = (f'Junction {point.number} / {SERVICE_NAMES[point.kind]}\n{STATUS_NAMES[point.status]} / {minutes(point.seconds)}\n'
                    f'Baseline {minutes(point.baseline_seconds)}' +
                    (f' / +{added / 60:.1f} min' if added is not None and math.isfinite(added) else '') +
                    f'\n{point.facility.name[:51] if point.facility else "No reachable mapped facility"}')
            button = ctk.CTkButton(self.body, text=text, command=lambda p=point: self.controller.focus(p),
                font=self.small_font, text_color=COLORS[point.status], fg_color='#15251a',
                hover_color='#233d29', anchor='w', corner_radius=2, height=92)
            button.pack(fill='x', padx=4, pady=3)
            self.rows.append(button)
        if not points:
            label = ctk.CTkLabel(self.body, text='No junctions exceed these thresholds.', font=self.small_font, text_color='#abd2ad')
            label.pack(pady=15)
            self.rows.append(label)
