"""Editable connection settings; API keys are masked and saved via DPAPI."""
import customtkinter as ctk

from .config import environment_values


class SettingsPanel:
    def __init__(self, app):
        self.app = app
        self.window = ctk.CTkToplevel(app)
        self.window.title('CityCollapse / Settings')
        self.window.configure(fg_color='#0c1510')
        scale = self.window._get_window_scaling()
        height = min(570, int((self.window.winfo_screenheight() - 120) / scale))
        self.window.geometry(f'500x{height}')
        self.window.minsize(420, 380)
        self.window.transient(app)
        self.window.protocol('WM_DELETE_WINDOW', self.window.withdraw)
        ctk.CTkLabel(self.window, text='CONNECTION SETTINGS', text_color='#abd2ad',
                     font=app.font).pack(pady=(16, 8))
        body = ctk.CTkScrollableFrame(self.window, fg_color='transparent',
                                     scrollbar_button_color='#3d5943')
        body.pack(fill='both', expand=True, padx=16)
        self.entries = {}
        for key, label, secret in (
            ('TOMTOM_API_KEY', 'TomTom API key / live traffic', True),
            ('VITE_CARTO_API_KEY', 'CARTO API key / basemap (optional)', True),
            ('OLLAMA_BASE_URL', 'Ollama server address', False),
            ('OLLAMA_MODEL', 'Ollama model', False),
        ):
            ctk.CTkLabel(body, text=label, text_color='#9bbca1', font=app.small_font,
                         anchor='w').pack(fill='x', padx=6, pady=(8, 2))
            entry = ctk.CTkEntry(body, font=app.small_font, height=34, show='*' if secret else '',
                fg_color='#15251a', border_color='#3d5943', text_color='#abd2ad')
            entry.pack(fill='x', padx=6)
            self.entries[key] = entry
        self.show_keys = ctk.CTkCheckBox(body, text='Show API keys', font=app.small_font,
            text_color='#9bbca1', command=self.toggle_keys, checkbox_width=18, checkbox_height=18)
        self.show_keys.pack(anchor='w', padx=6, pady=12)
        ctk.CTkLabel(body, text='Ollama must be installed separately with the selected model.\n'
                     'API keys are saved for your Windows account. Saved values override .env settings.',
                     text_color='#819487', font=app.small_font, wraplength=410, justify='left').pack(
                         fill='x', padx=6, pady=(0, 8))
        app.button(body, 'Basemap / offline options...', app.show_map_options, width=260).pack(pady=6)
        self.message = ctk.CTkLabel(self.window, text='', text_color='#9bbca1', font=app.small_font,
                                    wraplength=450, justify='left', height=42)
        self.message.pack(fill='x', padx=18, pady=(6, 0))
        actions = ctk.CTkFrame(self.window, fg_color='transparent')
        actions.pack(fill='x', padx=20, pady=(4, 16))
        self.save_button = app.button(actions, 'Save settings', self.save, width=150)
        self.save_button.pack(side='left')
        app.button(actions, 'Close', self.window.withdraw, width=90).pack(side='right')
        self.window.bind('<Control-s>', lambda event: self.save())
        self.reload()

    def reload(self):
        values = environment_values()
        defaults = {'OLLAMA_BASE_URL': 'http://127.0.0.1:11434', 'OLLAMA_MODEL': 'llama3.1:8b'}
        for key, entry in self.entries.items():
            entry.delete(0, 'end')
            value = values.get(key, defaults.get(key, ''))
            if key == 'TOMTOM_API_KEY':
                value = values.get(key) or values.get('CITYCOLLAPSE_TOMTOM_API_KEY', '')
            entry.insert(0, value)
        self.show_keys.deselect()
        self.toggle_keys()
        self.message.configure(text='Changes apply to new traffic requests. Clear a key and save to remove it.')

    def toggle_keys(self):
        for key in ('TOMTOM_API_KEY', 'VITE_CARTO_API_KEY'):
            self.entries[key].configure(show='' if self.show_keys.get() else '*')

    def show(self):
        self.reload()
        self.window.deiconify()
        self.window.lift()
        self.entries['TOMTOM_API_KEY'].focus_set()

    def save(self):
        values = {key: entry.get().strip() for key, entry in self.entries.items()}
        try:
            self.app.apply_connection_settings(values)
            self.message.configure(text='Settings saved. New analyses use these values.', text_color='#abd2ad')
        except (ValueError, OSError):
            # Show controlled validation errors, never provider URLs or key values.
            try:
                self.app.validate_connection_settings(values)
            except ValueError as error:
                self.message.configure(text=str(error), text_color='#e3a78f')
            else:
                self.message.configure(text='Could not save settings. Check access to your user settings folder.', text_color='#e3a78f')
