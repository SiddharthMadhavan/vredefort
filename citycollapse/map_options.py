"""Local basemap choices; shares the application's Tk event loop."""
from tkinter import filedialog
import customtkinter as ctk


class MapOptions:
    def __init__(self, app):
        self.app = app
        self.window = ctk.CTkToplevel(app)
        self.window.title('CityCollapse / Basemap')
        self.window.geometry('430x380')
        self.window.resizable(False, False)
        self.window.configure(fg_color='#0c1510')
        self.window.transient(app)
        self.window.protocol('WM_DELETE_WINDOW', self.window.withdraw)
        ctk.CTkLabel(self.window, text='BASEMAP', font=app.font, text_color='#abd2ad').pack(pady=(18, 6))
        self.description = ctk.CTkLabel(self.window, text='', font=app.small_font,
            text_color='#9bbca1', wraplength=390, justify='left')
        self.description.pack(padx=18, pady=6)
        for label, command in (
            ('Online map / reuse cached tiles', lambda: self.choose(False)),
            ('Offline / cached tiles only', lambda: self.choose(True)),
            ('Open local raster map pack...', self.open_pack),
        ):
            app.button(self.window, label, command, width=390).pack(pady=5)
        self.message = ctk.CTkLabel(self.window, text='', font=app.small_font,
            text_color='#9bbca1', wraplength=390, justify='left')
        self.message.pack(padx=18, pady=8)
        self.refresh()

    def refresh(self):
        tiles = self.app.tiles
        if not tiles:
            source = 'Basemap unavailable'
        elif tiles.local_path:
            source = 'Local map pack: ' + tiles.local_path.name
        else:
            source = 'Offline cache' if tiles.offline else 'Online + local cache'
        self.description.configure(text=source + '\nRoads and traffic playback are stored locally. Live traffic queries still need the internet.')
        self.message.configure(text='Offline coverage depends on the tiles already saved. Zooming in can reuse lower-resolution tiles. Local packs must contain raster tiles.')

    def show(self):
        self.refresh()
        self.window.deiconify()
        self.window.lift()

    def choose(self, offline, path=None):
        try:
            self.app.set_basemap(offline, path)
            self.refresh()
        except (ValueError, OSError) as error:
            self.message.configure(text=str(error))

    def open_pack(self):
        path = filedialog.askopenfilename(parent=self.window, title='Open raster MBTiles basemap',
            filetypes=[('Raster MBTiles', '*.mbtiles')])
        if path:
            self.choose(True, path)
