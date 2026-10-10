"""Agent-specific replies and evidence, with one pipeline progress indicator."""
import json
import customtkinter as ctk

from .markdown_text import MarkdownTextbox
from .agent_catalog import AGENTS, AGENT_BY_CHOICE
from .presentation import display_text, display_evidence


class AnalystPanel(ctk.CTkFrame):
    def __init__(self, parent, font, small_font, on_close):
        super().__init__(parent, fg_color='#0c1510', border_width=1,
                         border_color='#3d5943', corner_radius=0)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(5, weight=1)
        header = ctk.CTkFrame(self, fg_color='transparent')
        header.grid(row=0, column=0, padx=18, pady=(18, 6), sticky='ew')
        header.grid_columnconfigure(0, weight=1)
        self.heading = ctk.CTkLabel(header, text='01 / LIVE TRAFFIC ANALYST', font=font,
                                    text_color='#abd2ad', anchor='w', justify='left', wraplength=360)
        self.heading.grid(row=0, column=0, sticky='w')
        ctk.CTkButton(header, text='Close', width=64, command=on_close,
                      font=small_font, fg_color='#15251a', hover_color='#233d29',
                      text_color='#abd2ad').grid(row=0, column=1, padx=(10, 0))
        self.target = ctk.CTkLabel(self, text='', font=small_font, text_color='#abd2ad',
                                  justify='left', anchor='w', wraplength=360)
        self.target.grid(row=1, column=0, padx=18, pady=4, sticky='ew')
        self.status = ctk.CTkLabel(self, text='', font=small_font, text_color='#7eaf87',
                                  justify='left', anchor='w', wraplength=360)
        self.status.grid(row=2, column=0, padx=18, pady=(4, 8), sticky='ew')
        self.agent_picker = ctk.CTkOptionMenu(
            self, values=[spec.choice for spec in AGENTS], font=small_font, dropdown_font=small_font,
            command=self.select_agent, fg_color='#15251a', button_color='#33533c',
            button_hover_color='#41694c', dropdown_fg_color='#15251a',
            dropdown_hover_color='#33533c', text_color='#abd2ad', dropdown_text_color='#abd2ad')
        self.agent_picker.grid(row=3, column=0, padx=18, pady=(0, 8), sticky='ew')
        self.pipeline_status = ctk.CTkLabel(
            self, text='', font=small_font, text_color='#819487',
            justify='left', anchor='w', wraplength=360)
        self.pipeline_status.grid(row=4, column=0, padx=18, pady=(0, 4), sticky='ew')
        self.tabs = ctk.CTkTabview(
            self, fg_color='#0b100d', segmented_button_fg_color='#15251a',
            segmented_button_selected_color='#33533c',
            segmented_button_selected_hover_color='#41694c',
            text_color='#abd2ad', corner_radius=3)
        self.tabs.grid(row=5, column=0, padx=14, pady=(0, 18), sticky='nsew')
        self.tabs._segmented_button.configure(font=small_font)
        self.reply = self.textbox('Analysis', font, markdown=True)
        self.replies = {'live': self.reply}
        for spec in AGENTS[1:]:
            self.replies[spec.key] = MarkdownTextbox(
                self.tabs.tab('Analysis'), font=font, text_color='#abd2ad',
                fg_color='transparent', wrap='word', state='disabled')
        self.history_reply = self.replies['historical']
        self.evidence = self.textbox('Evidence', small_font)
        self.active_agent = 'live'
        self.visited_agents = {'live'}
        self.statuses = {spec.key: ('Waiting for analysis', False) for spec in AGENTS}
        self.evidences = {spec.key: None for spec in AGENTS}
        self.raw_replies = {spec.key: '' for spec in AGENTS}
        self.models = {spec.key: '' for spec in AGENTS}
        self.road_id = ''
        self.agent_picker.set('01 Live')
        self.bind('<Configure>', self.resize_labels)

    def textbox(self, name, font, markdown=False):
        tab = self.tabs.add(name)
        widget = MarkdownTextbox if markdown else ctk.CTkTextbox
        text = widget(tab, font=font, text_color='#abd2ad',
                      fg_color='transparent', wrap='word', state='disabled')
        text.pack(fill='both', expand=True)
        return text

    def resize_labels(self, event):
        width = max(150, event.width / self._get_widget_scaling() - 36)
        self.target.configure(wraplength=width)
        self.status.configure(wraplength=width)
        self.pipeline_status.configure(wraplength=width)
        self.heading.configure(wraplength=max(120, width - 84))

    @staticmethod
    def replace_text(widget, text):
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('end', text)
        widget.configure(state='disabled')

    def begin(self, road_id, model, history_model=None, models=None):
        self.road_id = road_id
        self.models = {spec.key: (models or {}).get(spec.key, model) for spec in AGENTS}
        self.models['historical'] = history_model or self.models['historical']
        self.statuses = {spec.key: ('Queued / waiting for earlier agents', False) for spec in AGENTS}
        self.statuses['live'] = ('Collecting live traffic...', False)
        self.evidences = {spec.key: None for spec in AGENTS}
        for reply in self.replies.values():
            reply.set_markdown('')
        self.raw_replies = {spec.key: '' for spec in AGENTS}
        self.visited_agents = {'live'}
        self.set_pipeline_status('Starting traffic analysis...')
        self.agent_picker.set('01 Live')
        self.select_agent('01 Live')
        self.tabs.set('Analysis')

    def select_agent(self, choice):
        spec = AGENT_BY_CHOICE[choice]
        self.active_agent = spec.key
        self.agent_picker.set(choice)
        self.heading.configure(text=f'{choice[:2]} / {spec.title}')
        self.target.configure(text=f'{self.road_id}\nOllama / {self.models[self.active_agent]}' +
                              (f'\n{spec.badge}' if spec.badge else ''))
        for reply in self.replies.values():
            reply.pack_forget()
        self.replies[self.active_agent].pack(fill='both', expand=True)
        if self.active_agent not in self.visited_agents:
            self.replies[self.active_agent].yview_moveto(0)
            self.visited_agents.add(self.active_agent)
        self.set_status(*self.statuses[self.active_agent], agent=self.active_agent)
        evidence = self.evidences[self.active_agent]
        self.replace_text(self.evidence, json.dumps(display_evidence(evidence), indent=2, ensure_ascii=False) if evidence else 'Waiting for traffic evidence...')

    def set_status(self, text, error=False, agent='live'):
        self.statuses[agent] = (text, error)
        if agent == self.active_agent:
            self.status.configure(text=display_text(text), text_color='#e4a58e' if error else '#7eaf87')

    def set_pipeline_status(self, text):
        self.pipeline_status.configure(text=display_text(text))

    def set_evidence(self, evidence, agent='live'):
        self.evidences[agent] = evidence
        if agent == self.active_agent:
            self.replace_text(self.evidence, json.dumps(display_evidence(evidence), indent=2, ensure_ascii=False))
        if agent in ('live', 'historical') and evidence.get('available_samples') == 0:
            message = 'Historical baseline unavailable for these edges' if agent == 'historical' else 'Live measurements unavailable / Ollama will assess the evidence gaps'
            self.set_status(message, error=True, agent=agent)

    def append(self, text, agent='live'):
        self.raw_replies[agent] += text
        reply = self.replies[agent]
        reply.set_markdown(display_text(self.raw_replies[agent]), follow=reply.yview()[1] >= .98)
