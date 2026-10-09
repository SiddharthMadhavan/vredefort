"""Local datasets and a spatial index. No network or GUI dependencies."""
from dataclasses import dataclass
import json
from pathlib import Path
from .geometry import project, cumulative_lengths

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'

@dataclass(frozen=True, slots=True)
class Road:
    id: str
    properties: dict
    paths: tuple
    bounds: tuple

class SpatialIndex:
    """Grid lookup avoids scanning all geometry on every hover and pan."""
    def __init__(self, bounds, cells=32768):
        self.cells, self.entries, self.global_ids = cells, {}, set()
        for index, box in enumerate(bounds):
            x1, y1, x2, y2 = self.box_cells(box)
            if (x2 - x1 + 1) * (y2 - y1 + 1) > 256:
                self.global_ids.add(index)
                continue
            for x in range(x1, x2 + 1):
                for y in range(y1, y2 + 1):
                    self.entries.setdefault((x, y), set()).add(index)

    def box_cells(self, box):
        return tuple(int(value * self.cells) for value in box)

    def query(self, box):
        x1, y1, x2, y2 = self.box_cells(box)
        result = set(self.global_ids)
        # Zoomed-out views can cover many empty grid cells; iterate occupied cells then.
        if (x2 - x1 + 1) * (y2 - y1 + 1) > len(self.entries) * 2:
            for (x, y), indices in self.entries.items():
                if x1 <= x <= x2 and y1 <= y <= y2:
                    result.update(indices)
        else:
            for x in range(x1, x2 + 1):
                for y in range(y1, y2 + 1):
                    result.update(self.entries.get((x, y), ()))
        return result

def load_json(name):
    with (DATA / name).open(encoding='utf-8') as stream:
        return json.load(stream)

def read_roads(name):
    collection = load_json(name)
    if collection.get('type') != 'FeatureCollection':
        raise ValueError(f'Invalid road dataset: {name}')
    roads = []
    for feature in collection['features']:
        geometry = feature['geometry']
        if geometry['type'] not in ('LineString', 'MultiLineString'):
            raise ValueError(f'Unexpected road geometry in {name}')
        lines = [geometry['coordinates']] if geometry['type'] == 'LineString' else geometry['coordinates']
        paths = tuple(tuple(project(*point[:2]) for point in line) for line in lines)
        points = [point for path in paths for point in path]
        if not points:
            raise ValueError('Empty road geometry')
        xs, ys = zip(*points)
        roads.append(Road(str(feature['properties']['id']), feature['properties'], paths, (min(xs), min(ys), max(xs), max(ys))))
    return roads, SpatialIndex(road.bounds for road in roads)

def read_points(name):
    collection = load_json(name)
    if collection.get('type') != 'FeatureCollection':
        raise ValueError(f'Invalid point dataset: {name}')
    points = []
    for feature in collection['features']:
        if feature['geometry']['type'] != 'Point':
            raise ValueError(f'Unexpected point geometry in {name}')
        coordinate = feature['geometry']['coordinates'][:2]
        points.append({**feature['properties'], 'coordinate': coordinate, 'point': project(*coordinate)})
    return points, SpatialIndex((*point['point'], *point['point']) for point in points)

def load_datasets():
    views = {}
    for mode, file in [('KML width shading', 'bengaluru-road-widths.geojson'), ('KML road graph', 'bengaluru-kml-road-edges.geojson'), ('OSM road graph', 'bengaluru-road-edges.geojson')]:
        roads, index = read_roads(file)
        node_file = 'bengaluru-road-nodes.geojson' if mode == 'OSM road graph' else 'bengaluru-kml-road-nodes.geojson'
        nodes, node_index = read_points(node_file)
        views[mode] = {'roads': roads, 'index': index, 'by_id': {road.id: road for road in roads}, 'nodes': nodes, 'node_index': node_index}
    graph = load_json('bengaluru-kml-road-graph.json')
    for edge in graph['edges']:
        edge['cumulative'] = cumulative_lengths(edge['coordinates'])
    return {'views': views, 'graph': graph, 'hospitals': read_points('bengaluru-hospitals.geojson')[0], 'fire': read_points('bengaluru-fire-stations.geojson')[0], 'width_metadata': load_json('bengaluru-road-widths.metadata.json'), 'hospital_metadata': load_json('bengaluru-hospitals.metadata.json')}
