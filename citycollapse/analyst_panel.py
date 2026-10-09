"""Two independent analyst replies, sharing a read-only evidence viewer."""
import json
import customtkinter as ctk

from .markdown_text import MarkdownTextbox


class AnalystPanel(ctk.CTkFrame):
    def __init__(self, parent, font, small_font, on_close):
        super().__init__(parent, fg_color='#0c1510', border_width=1,
                         border_color='#3d5943', corner_radius=0)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)
        header = ctk.CTkFrame(self, fg_color='transparent')
        header.grid(row=0, column=0, padx=18, pady=(18, 6), sticky='ew')
        header.grid_columnconfigure(0, weight=1)
        self.heading = ctk.CTkLabel(header, text='01 / LIVE TRAFFIC ANALYST', font=font,
                                    text_color='#abd2ad', anchor='w')
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
        self.agent_picker = ctk.CTkSegmentedButton(
            self, values=['01 Live', '02 History (synthetic)'], font=small_font,
            command=self.select_agent, fg_color='#15251a', selected_color='#33533c',
            selected_hover_color='#41694c', text_color='#abd2ad')
        self.agent_picker.grid(row=3, column=0, padx=18, pady=(0, 8), sticky='ew')
        self.tabs = ctk.CTkTabview(
            self, fg_color='#0b100d', segmented_button_fg_color='#15251a',
            segmented_button_selected_color='#33533c',
            segmented_button_selected_hover_color='#41694c',
            text_color='#abd2ad', corner_radius=3)
        self.tabs.grid(row=4, column=0, padx=14, pady=(0, 18), sticky='nsew')
        self.tabs._segmented_button.configure(font=small_font)
        self.reply = self.textbox('Analysis', font, markdown=True)
        self.history_reply = MarkdownTextbox(
            self.tabs.tab('Analysis'), font=font, text_color='#abd2ad',
            fg_color='transparent', wrap='word', state='disabled')
        self.evidence = self.textbox('Evidence', small_font)
        self.active_agent = 'live'
        self.statuses = {'live': ('', False), 'historical': ('Synthetic baseline / waiting for analysis', False)}
        self.evidences = {'live': None, 'historical': None}
        self.models = {'live': '', 'historical': ''}
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

    @staticmethod
    def replace_text(widget, text):
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('end', text)
        widget.configure(state='disabled')

    def begin(self, road_id, model, history_model=None):
        self.road_id = road_id
        self.models = {'live': model, 'historical': history_model or model}
        self.statuses = {'live': ('Collecting live traffic...', False),
                         'historical': ('Queued / synthetic historical baseline', False)}
        self.evidences = {'live': None, 'historical': None}
        self.reply.set_markdown('')
        self.history_reply.set_markdown('')
        self.agent_picker.set('01 Live')
        self.select_agent('01 Live')
        self.tabs.set('Analysis')

    def select_agent(self, choice):
        self.active_agent = 'historical' if choice.startswith('02') else 'live'
        historical = self.active_agent == 'historical'
        self.heading.configure(text='02 / HISTORICAL TRAFFIC ANALYST' if historical else '01 / LIVE TRAFFIC ANALYST')
        self.target.configure(text=f'{self.road_id}\nOllama / {self.models[self.active_agent]}' +
                              ('\nSYNTHETIC DATA / DEMONSTRATION ONLY' if historical else ''))
        self.reply.pack_forget()
        self.history_reply.pack_forget()
        (self.history_reply if historical else self.reply).pack(fill='both', expand=True)
        self.set_status(*self.statuses[self.active_agent], agent=self.active_agent)
        evidence = self.evidences[self.active_agent]
        self.replace_text(self.evidence, json.dumps(evidence, indent=2, ensure_ascii=False) if evidence else 'Waiting for traffic evidence...')

    def set_status(self, text, error=False, agent='live'):
        self.statuses[agent] = (text, error)
        if agent == self.active_agent:
            self.status.configure(text=text, text_color='#e4a58e' if error else '#7eaf87')

    def set_evidence(self, evidence, agent='live'):
        self.evidences[agent] = evidence
        if agent == self.active_agent:
            self.replace_text(self.evidence, json.dumps(evidence, indent=2, ensure_ascii=False))
        if not evidence['available_samples']:
            message = 'Synthetic history unavailable for these edges' if agent == 'historical' else 'Live measurements unavailable / Ollama will assess the evidence gaps'
            self.set_status(message, error=True, agent=agent)

    def append(self, text, agent='live'):
        (self.history_reply if agent == 'historical' else self.reply).append_markdown(text)
