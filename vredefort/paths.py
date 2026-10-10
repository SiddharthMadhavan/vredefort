"""Read-only bundled resources and persistent, per-user runtime files."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
FROZEN = bool(getattr(sys, 'frozen', False))
ENV_ROOT = Path(sys.executable).resolve().parent if FROZEN else ROOT
USER_DIR = Path(os.environ.get('VREDEFORT_USER_DIR') or
                str(Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'Vredefort'))
CACHE_DIR = USER_DIR / 'cache' if FROZEN else ROOT / '.cache'
