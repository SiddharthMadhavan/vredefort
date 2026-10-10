"""Launch the built application from an unrelated working directory."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parent.parent
report = root / '.tmp' / 'executable-smoke.json'
report.parent.mkdir(exist_ok=True)
if report.exists():
    report.unlink()
executable = root / 'dist' / 'CityCollapse.exe'
assert executable.is_file(), 'Build CityCollapse.spec first'
with tempfile.TemporaryDirectory() as working:
    completed = subprocess.run([str(executable), '--self-test', str(report)], cwd=working,
        creationflags=subprocess.CREATE_NO_WINDOW, timeout=100)
    assert report.exists(), 'Executable failed before creating its self-test report'
    result = json.loads(report.read_text())
    assert completed.returncode == 0 and result['status'] == 'passed', result
    assert result['frozen'] and result['bundled_env_absent'] and result['persistent_cache']
    print('Executable smoke passed: standalone launch, bundled graph/fonts/datasets, '
          'encrypted API settings, validation, key clearing, simulation and road closure.', flush=True)
