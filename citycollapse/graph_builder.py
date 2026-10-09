"""Pure-Python graph conversion, preserving stored-coordinate connectivity only."""
from collections import defaultdict
import math
from .geometry import distance_metres

def build_graph(collection, exact=False):
    def key(point):
        if exact:
            return 'kml_n_' + '_'.join(str(value).removesuffix('.0') for value in point)
        return f'n_{math.floor(point[0] * 1e5 + .5)}_{math.floor(point[1] * 1e5 + .5)}'
    positions, occurrences, candidates, roads = {}, defaultdict(int), set(), []
    excluded = []
    index = 0
    for feature in collection['features']:
        geometry = feature['geometry']
        lines = [geometry['coordinates']] if geometry['type'] == 'LineString' else geometry['coordinates'] if geometry['type'] == 'MultiLineString' else None
        if lines is None:
            raise ValueError('Only line geometry can form a road graph')
        for part, line in enumerate(lines):
            path = []
            for point in line:
                if len(point) != 2 or not all(math.isfinite(value) for value in point):
                    raise ValueError('Invalid coordinate')
                if not path or key(point) != key(path[-1]):
                    path.append(point)
            source_id = f'{feature["properties"]["id"]}_part_{part}' if geometry['type'] == 'MultiLineString' else feature.get('id', index)
            if len(path) < 2:
                excluded.append(source_id)
            else:
                for point in path:
                    positions.setdefault(key(point), point)
                    occurrences[key(point)] += 1
                candidates.update([key(path[0]), key(path[-1])])
                roads.append((index, path, source_id, feature['properties']))
            index += 1
    candidates.update(point for point, count in occurrences.items() if count > 1)
    segments = {}
    incidence = defaultdict(list)
    for index, path, source_id, properties in roads:
        start = 0
        for end in range(1, len(path)):
            if key(path[end]) not in candidates:
                continue
            identifier = f'e_{index}_{start}_{end}'
            edge = {'id': identifier, 'source': key(path[start]), 'target': key(path[end]), 'coordinates': path[start:end + 1], 'source_feature_id': source_id, 'properties': properties}
            segments[identifier] = edge
            incidence[edge['source']].append(identifier)
            incidence[edge['target']].append(identifier)
            start = end
    anchors = {point for point in candidates if len(incidence[point]) != 2}
    seen = set()
    for point in sorted(candidates, key=lambda point: positions[point]):
        if point in seen:
            continue
        queue = [point]; seen.add(point)
        for current in queue:
            for identifier in incidence[current]:
                edge = segments[identifier]
                other = edge['target'] if edge['source'] == current else edge['source']
                if other not in seen:
                    seen.add(other); queue.append(other)
        if not any(point in anchors for point in queue):
            anchors.add(queue[0])
    used, edges = set(), []
    for point in sorted(anchors, key=lambda point: positions[point]):
        for first in incidence[point]:
            if first in used:
                continue
            current, identifier, parts, coordinates = point, first, [], []
            while True:
                used.add(identifier)
                edge = segments[identifier]
                parts.append(edge)
                path = edge['coordinates'] if edge['source'] == current else list(reversed(edge['coordinates']))
                coordinates.extend(path if not coordinates else path[1:])
                current = edge['target'] if edge['source'] == current else edge['source']
                if current in anchors:
                    break
                identifier = next(candidate for candidate in incidence[current] if candidate != edge['id'])
            ids = [part['id'] for part in parts]
            features = list(dict.fromkeys(part['source_feature_id'] for part in parts))
            identifier = ids[0] if len(ids) == 1 else 'merged_' + min(ids)
            length = sum(distance_metres(a, b) for a, b in zip(coordinates, coordinates[1:]))
            highways = list(dict.fromkeys(part['properties'].get('highway') for part in parts if part['properties'].get('highway')))
            names = list(dict.fromkeys(part['properties'].get('name') for part in parts if part['properties'].get('name')))
            output = {'id': ('kml_' if exact else '') + identifier, 'source': point, 'target': current, 'length_m': round(length, 3), 'coordinates': coordinates, 'source_edge_ids': ids, 'source_feature_ids': features, 'highways': highways, 'highway': highways[0] if len(highways) == 1 else None, 'names': names}
            if exact:
                output['kml_road_ids'] = list(dict.fromkeys(part['properties']['id'] for part in parts))
            edges.append(output)
    final_incidence = defaultdict(list)
    for edge in edges:
        final_incidence[edge['source']].append(edge['id'])
        final_incidence[edge['target']].append(edge['id'])
    nodes = []
    for number, point in enumerate(sorted(anchors, key=lambda point: positions[point]), 1):
        degree = len(final_incidence[point])
        nodes.append({'id': point, 'number': number, 'lon': positions[point][0], 'lat': positions[point][1], 'degree': degree, 'edge_ids': list(dict.fromkeys(final_incidence[point])), 'kind': 'junction_candidate' if degree >= 3 else 'endpoint' if degree == 1 else 'loop_anchor'})
    return {'schema_version': 2, 'directed': False, 'multigraph': True, 'coordinate_reference_system': 'EPSG:4326', 'nodes': nodes, 'edges': edges, 'excluded_source_features': excluded}

