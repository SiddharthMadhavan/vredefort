"""The Live Traffic Analyst's read-only response and evidence panel."""
import json
import customtkinter as ctk

from .markdown_text import MarkdownTextbox


class AnalystPanel(ctk.CTkFrame):
    def __init__(self, parent, font, small_font, on_close):
        super().__init__(parent, fg_color='#0c1510', border_width=1,
                         border_color='#3d5943', corner_radius=0)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        header = ctk.CTkFrame(self, fg_color='transparent')
        header.grid(row=0, column=0, padx=18, pady=(18, 6), sticky='ew')
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text='01 / LIVE TRAFFIC ANALYST', font=font,
                     text_color='#abd2ad', anchor='w').grid(row=0, column=0, sticky='w')
        ctk.CTkButton(header, text='Close', width=64, command=on_close,
                      font=small_font, fg_color='#15251a', hover_color='#233d29',
                      text_color='#abd2ad').grid(row=0, column=1, padx=(10, 0))
        self.target = ctk.CTkLabel(self, text='', font=small_font, text_color='#abd2ad',
                                  justify='left', anchor='w', wraplength=360)
        self.target.grid(row=1, column=0, padx=18, pady=4, sticky='ew')
        self.status = ctk.CTkLabel(self, text='', font=small_font, text_color='#7eaf87',
                                  justify='left', anchor='w', wraplength=360)
        self.status.grid(row=2, column=0, padx=18, pady=(4, 8), sticky='ew')
        self.tabs = ctk.CTkTabview(
            self, fg_color='#0b100d', segmented_button_fg_color='#15251a',
            segmented_button_selected_color='#33533c',
            segmented_button_selected_hover_color='#41694c',
            text_color='#abd2ad', corner_radius=3)
        self.tabs.grid(row=3, column=0, padx=14, pady=(0, 18), sticky='nsew')
        self.tabs._segmented_button.configure(font=small_font)
        self.reply = self.textbox('Analysis', font, markdown=True)
        self.evidence = self.textbox('Evidence', small_font)
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

    def begin(self, road_id, model):
        self.target.configure(text=f'{road_id}\nOllama / {model}')
        self.set_status('Collecting live traffic...')
        self.reply.set_markdown('')
        self.replace_text(self.evidence, 'Waiting for traffic evidence...')
        self.tabs.set('Analysis')

    def set_status(self, text, error=False):
        self.status.configure(text=text, text_color='#e4a58e' if error else '#7eaf87')

    def set_evidence(self, evidence):
        self.replace_text(self.evidence, json.dumps(evidence, indent=2, ensure_ascii=False))
        if not evidence['available_samples']:
            self.set_status('Live measurements unavailable / Ollama will assess the evidence gaps', error=True)

    def append(self, text):
        self.reply.append_markdown(text)
