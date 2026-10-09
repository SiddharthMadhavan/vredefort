"""Small, native Markdown viewer for streamed analyst prose (no HTML/browser)."""
import re

import customtkinter as ctk


INLINE = re.compile(
    r'\\([\\`*_{}\[\]()#+.!>~-])'
    r'|(`+)(.+?)\2'
    r'|\[([^\]\n]+)\]\((https?://[^\s)]+)\)'
    r'|(?<!\w)(\*\*\*|___)(?=\S)(.+?)(?<=\S)\6(?!\w)'
    r'|(\*\*|__)(?=\S)(.+?)(?<=\S)\8(?![*_])'
    r'|(?<!\w)(\*|_)(?=\S)(.+?)(?<=\S)\10(?!\w)'
    r'|~~(?=\S)(.+?)(?<=\S)~~')


def inline_runs(text, tags=()):
    """Yield (visible text, style tags); leave unfinished stream syntax literal."""
    position = 0
    for match in INLINE.finditer(text):
        if match.start() > position:
            yield text[position:match.start()], tags
        if match.group(1) is not None:
            yield match.group(1), tags
        elif match.group(2):
            yield match.group(3), tags + ('code',)
        elif match.group(4):
            yield from inline_runs(match.group(4), tags + ('link',))
            yield f' ({match.group(5)})', tags + ('link',)
        elif match.group(6):
            yield from inline_runs(match.group(7), tags + ('strong_emphasis',))
        elif match.group(8):
            yield from inline_runs(match.group(9), tags + ('strong',))
        elif match.group(10):
            style = 'strong_emphasis' if 'strong' in tags else 'emphasis'
            yield from inline_runs(match.group(11), tags + (style,))
        else:
            yield from inline_runs(match.group(12), tags + ('strike',))
        position = match.end()
    if position < len(text):
        yield text[position:], tags


def markdown_runs(source):
    """Render the Markdown used in analyst replies, preserving code and road IDs."""
    fence = None
    for line in source.splitlines(keepends=True):
        content = line.rstrip('\r\n')
        newline = '\n' if line.endswith(('\n', '\r')) else ''
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})(.*)$', content)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            else:
                yield content + newline, ('code_block',)
            continue
        if marker:
            fence = marker[1]
            continue
        if re.fullmatch(r'\s{0,3}([-*_])(?:\s*\1){2,}\s*', content):
            yield '\u2500' * 24 + newline, ('rule',)
            continue
        tags = ()
        heading = re.match(r'^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$', content)
        if heading:
            content = heading[2]
            tags = (f'heading{min(len(heading[1]), 3)}',)
        else:
            quote = re.match(r'^\s{0,3}>\s?(.*)$', content)
            if quote:
                content = quote[1]
                tags = ('quote',)
            bullet = re.match(r'^(\s*)(?:[-+*]|(\d+)[.)])\s+(.*)$', content)
            if bullet:
                prefix = f'{bullet[2]}. ' if bullet[2] else '\u2022 '
                yield bullet[1] + prefix, tags + ('list',)
                content = bullet[3]
                tags += ('list',)
        yield from inline_runs(content, tags)
        if newline:
            yield newline, tags


class MarkdownTextbox(ctk.CTkTextbox):
    """Read-only CTk textbox with Markdown tags and DPI-aware native text fonts."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.source = ''
        self._markdown_ready = True
        self._style_tags()

    def _update_font(self):
        super()._update_font()
        if getattr(self, '_markdown_ready', False):
            self._style_tags()

    def _set_scaling(self, *args, **kwargs):
        super()._set_scaling(*args, **kwargs)
        if getattr(self, '_markdown_ready', False):
            self._style_tags()

    def _style_tags(self):
        scale = self._get_widget_scaling()
        family, pixels, _ = self._apply_font_scaling(self._font)
        size = abs(pixels)
        styles = {
            'heading1': dict(font=(family, -round(size + 8 * scale), 'bold'), foreground='#dcf6df', spacing1=12 * scale, spacing3=6 * scale),
            'heading2': dict(font=(family, -round(size + 4 * scale), 'bold'), foreground='#dcf6df', spacing1=10 * scale, spacing3=5 * scale),
            'heading3': dict(font=(family, -size, 'bold'), foreground='#dcf6df', spacing1=8 * scale, spacing3=4 * scale),
            'strong': dict(font=(family, -size, 'bold'), foreground='#dcf6df'),
            'emphasis': dict(font=(family, -size, 'italic')),
            'strong_emphasis': dict(font=(family, -size, 'bold italic'), foreground='#dcf6df'),
            'strike': dict(overstrike=True),
            'code': dict(background='#17271c', foreground='#d1ebbc'),
            'code_block': dict(background='#17271c', foreground='#d1ebbc', lmargin1=10 * scale, lmargin2=10 * scale),
            'list': dict(lmargin1=8 * scale, lmargin2=26 * scale, spacing3=3 * scale),
            'quote': dict(foreground='#8fae96', lmargin1=14 * scale, lmargin2=14 * scale),
            'link': dict(foreground='#9de7b3', underline=True),
            'rule': dict(foreground='#3d5943', spacing1=5 * scale, spacing3=5 * scale),
        }
        # CTk's public tag_config deliberately disallows font settings. Apply them
        # to its native Text widget here, refreshing on CTk font/scaling changes.
        for name, options in styles.items():
            self._textbox.tag_configure(name, **options)

    def set_markdown(self, source, follow=False):
        top = self.index('@0,0')
        selection = self.tag_ranges('sel')
        self.source = source
        self.configure(state='normal')
        self.delete('1.0', 'end')
        for text, tags in markdown_runs(source):
            self.insert('end', text, tags)
        if selection:
            self.tag_add('sel', *selection)
        if follow:
            self.see('end')
        else:
            self.yview(top)
        self.configure(state='disabled')

    def append_markdown(self, text):
        # Reparse the accumulated reply because emphasis/fences may span chunks.
        self.set_markdown(self.source + text, follow=self.yview()[1] >= .98)
