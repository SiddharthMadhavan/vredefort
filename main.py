"""Run Vredefort: python main.py, or the standalone Windows executable."""
import os
from pathlib import Path
import sys
import tempfile


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        # Exercise the packaged UI without touching the user's saved keys or
        # contacting external map/traffic services.
        with tempfile.TemporaryDirectory(prefix='vredefort-check-') as temporary:
            os.environ['VREDEFORT_USER_DIR'] = temporary
            os.environ['VREDEFORT_MAP_OFFLINE'] = 'true'
            os.environ['VREDEFORT_MAP_PATH'] = ''
            from vredefort.diagnostics import run_self_test
            return run_self_test(Path(sys.argv[2]).resolve())
    from vredefort.app import VredefortApp
    VredefortApp().mainloop()
    return 0

if __name__ == '__main__':
    sys.exit(main())
