"""Exercise native formatting, split stream tokens, scrolling, and DPI changes."""
from pathlib import Path
import ctypes
import json
import os
import sys
from tkinter import font as tkfont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import customtkinter as ctk
from citycollapse.analyst_panel import AnalystPanel
from citycollapse.map_renderer import FONT_FILE


if sys.platform == 'win32' and FONT_FILE.exists():
    ctypes.windll.gdi32.AddFontResourceExW(str(FONT_FILE), 0x10, 0)
ctk.set_appearance_mode('dark')
app = ctk.CTk()
app.geometry('680x720')
family = 'VT323' if 'VT323' in tkfont.families(app) else 'Courier New'
panel = AnalystPanel(app, ctk.CTkFont(family, 20),
                     ctk.CTkFont(family, 17), app.destroy)
panel.pack(fill='both', expand=True)
app.update()
try:
    panel.begin('kml_merged_e_20022_0_1', 'llama3.1:8b')
    for chunk in ['## Current situation\n\n- Speed: **2', '8 km/h**\n',
                  '- Delay: *none reported*.\n\n',
                  '### Data freshness\n`kml_merged_e_20022_0_1`\n',
                  '> Observation age is unknown.\n\n```json\n',
                  '{"currentSpeed": 28}\n```\n']:
        panel.append(chunk)
        app.update()
    reply = panel.reply
    content = reply.get('1.0', 'end-1c')
    assert '**' not in content and '##' not in content and '```' not in content
    assert '- Speed: 28 km/h' in content
    for tag in ('heading2', 'heading3', 'strong', 'emphasis', 'list', 'code', 'code_block', 'quote'):
        assert reply.tag_ranges(tag), f'Missing rendered style: {tag}'
    old_font = reply.tag_cget('heading2', 'font')
    ctk.set_widget_scaling(1.25)
    app.update()
    assert reply.tag_cget('heading2', 'font') != old_font, 'Markdown font did not scale'
    ctk.set_widget_scaling(1)
    panel.set_evidence({'available_samples': 1, 'example': '**raw JSON**'})
    assert json.loads(panel.evidence.get('1.0', 'end'))['example'] == '**raw JSON**'
    reply.insert('end', 'UNAUTHORIZED EDIT')
    assert reply.get('1.0', 'end-1c') == content, 'Analysis must remain read-only'
    if os.environ.get('CITYCOLLAPSE_SMOKE_SCREENSHOT') and sys.platform == 'win32':
        from PIL import ImageGrab
        app.lift()
        app.update()
        Path('.tmp').mkdir(exist_ok=True)
        ImageGrab.grab(window=app.winfo_id()).save('.tmp/markdown-smoke.png')
    panel.append('\n' + 'Example paragraph.\n' * 100)
    app.update()
    reply.yview_moveto(.2)
    app.update()
    top = reply.index('@0,0')
    panel.append('More streaming text.\n')
    app.update()
    assert reply.index('@0,0') == top, 'New tokens moved a reader who scrolled up'
    panel.append('## Network reply\n' + 'Example network paragraph.\n' * 100, agent='network')
    panel.select_agent('03 Network bottlenecks')
    app.update()
    assert panel.replies['network'].yview()[0] <= .02, 'An unread agent reply should open at the beginning'
    panel.begin('new-road', 'llama3.1:8b')
    panel.append('Fresh reply')
    assert reply.source == 'Fresh reply' and reply.get('1.0', 'end-1c') == 'Fresh reply'
    panel.append('\nSyn')
    panel.append('thetic baseline')
    assert 'synthetic' not in reply.source.lower()
    assert 'model-generated baseline' in reply.source
    assert 'Synthetic baseline' in panel.raw_replies['live']
    print('Markdown GUI smoke passed: styles, streamed delimiters, DPI scaling, '
          'raw evidence, read-only text, scroll preservation, and response reset.')
finally:
    app.destroy()
