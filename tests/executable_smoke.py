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
executable = root / 'dist' / 'Vredefort.exe'
assert executable.is_file(), 'Build Vredefort.spec first'
with tempfile.TemporaryDirectory() as working:
    completed = subprocess.run([str(executable), '--self-test', str(report)], cwd=working,
        creationflags=subprocess.CREATE_NO_WINDOW, timeout=100)
    assert report.exists(), 'Executable failed before creating its self-test report'
    result = json.loads(report.read_text())
    assert completed.returncode == 0 and result['status'] == 'passed', result
    assert result['frozen'] and result['bundled_env_absent'] and result['persistent_cache']
    assert result['emergency_access'] and result['emergency_route'] and result['app_title'].startswith('Vredefort')
    assert result['healthcare_locations'] == 255
    assert result['nearest_road_entrances'] and result['emergency_facilities'] == 276
    print('Executable smoke passed: standalone launch, bundled graph/fonts/datasets, '
          'encrypted API settings, validation, key clearing, simulation, road closure, emergency access and title.', flush=True)
