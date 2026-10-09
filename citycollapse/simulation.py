"""Python replacement for the C++ vehicle backend; called directly from the Tk tick."""
from dataclasses import dataclass
import math
import random
from .geometry import position_along

@dataclass(slots=True)
class Vehicle:
    id: str
    edge: dict
    distance_m: float
    stopped: bool = False

    def position(self):
        return position_along(self.edge['coordinates'], self.edge['cumulative'], self.distance_m, self.edge['length_m'])

class Simulation:
    def __init__(self, graph):
        self.edges = [edge for edge in graph['edges'] if edge['length_m'] > 0 and edge['cumulative'][-1] > 0]
        if not self.edges:
            raise ValueError('Simulation requires a nonempty road graph')
        self.vehicles = []
        self.elapsed_s = 0.0

    def initialize_cars(self, count=5, seed=None):
        if not isinstance(count, int) or not 1 <= count <= 10000:
            raise ValueError('Car count must be between 1 and 10000')
        rng = random.Random(seed)
        # Preserve the original backend: first five edges, random distances.
        # Larger counts cycle through the existing edge list; no fabricated roads.
        self.vehicles = [Vehicle(f'vehicle_{i + 1}', self.edges[i % len(self.edges)], rng.uniform(0, self.edges[i % len(self.edges)]['length_m'])) for i in range(count)]
        self.elapsed_s = 0.0
        return self.vehicles

    def get_next_state(self, dt, speed_mps=100.0):
        if not math.isfinite(dt) or dt < 0 or not math.isfinite(speed_mps) or speed_mps < 0:
            raise ValueError('Time and speed must be finite and nonnegative')
        for vehicle in self.vehicles:
            vehicle.distance_m = min(vehicle.edge['length_m'], vehicle.distance_m + dt * speed_mps)
            vehicle.stopped = vehicle.distance_m >= vehicle.edge['length_m']
        self.elapsed_s += dt
        return self.vehicles
