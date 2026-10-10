# Build with: .venv/Scripts/python.exe -m PyInstaller Vredefort.spec
# Explicit resource list excludes .env, saved keys, caches, and development files.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

project = Path(SPECPATH)
resources = [(str(project / 'data'), 'data'), (str(project / 'assets'), 'assets')]
resources += collect_data_files('customtkinter')

a = Analysis([str(project / 'main.py')], pathex=[str(project)],
             binaries=[], datas=resources, hiddenimports=[], hookspath=[],
             hooksconfig={}, runtime_hooks=[], excludes=[])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='Vredefort',
          debug=False, strip=False, upx=False, console=False,
          disable_windowed_traceback=False)
