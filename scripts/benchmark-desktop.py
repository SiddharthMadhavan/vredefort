"""Measure movement + Pillow vehicle painting, excluding Tk image transfer."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from citycollapse.data import load_datasets
from citycollapse.simulation import Simulation
from citycollapse.map_renderer import Camera, paint_cars
from citycollapse.geometry import project

data = load_datasets()
simulation = Simulation(data['graph'])
camera = Camera(*project(77.5946, 12.9716), 11, 1400, 900)
print('Movement + vehicle bitmap at 1400x900; excludes Tk transfer and basemap painting:')
for count in [100, 1000, 10000]:
    simulation.initialize_cars(count, seed=42)
    started = time.perf_counter()
    for _ in range(5):
        simulation.get_next_state(1 / 30, 15)
        image, hits = paint_cars(camera, simulation.vehicles)
    print(f'{count:5} cars: {(time.perf_counter() - started) / 5 * 1000:.1f} ms/frame ({len(hits)} visible)')
