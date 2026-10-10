"""Immutable analysis scopes and deterministic connected-area context."""
from dataclasses import dataclass

MAX_AREA_ROADS = 12
MAX_AREA_SAMPLES = 16


@dataclass(frozen=True)
class AnalysisScope:
    kind: str
    identifiers: tuple[str, ...]

    @classmethod
    def junction(cls, identifier):
        return cls('junction', (identifier,))

    @classmethod
    def area(cls, identifiers):
        return cls('area', tuple(sorted(set(identifiers))))


def road_details(road):
    return {'id': road.id, 'names': road.properties.get('names') or [],
            **{key: road.properties[key] for key in ('length_m', 'source', 'target')}}


def connected_roads(network, identifiers):
    identifiers = set(identifiers)
    if not identifiers or not identifiers <= network.roads_by_id.keys():
        return False
    pending, seen = [min(identifiers)], set()
    while pending:
        identifier = pending.pop()
        if identifier in seen:
            continue
        seen.add(identifier)
        road = network.roads_by_id[identifier]
        for node in (road.properties['source'], road.properties['target']):
            pending.extend(edge for edge in network.edge_ids[node] if edge in identifiers and edge not in seen)
    return seen == identifiers


def scope_roads(network, scope):
    if isinstance(scope, str):
        if scope not in network.roads_by_id:
            raise ValueError('Selected road is unavailable')
        return (scope,)
    if not isinstance(scope, AnalysisScope):
        raise ValueError('Invalid analysis selection')
    if scope.kind == 'junction':
        if len(scope.identifiers) != 1 or scope.identifiers[0] not in network.nodes_by_id:
            raise ValueError('Selected junction is unavailable')
        identifiers = tuple(sorted(set(network.edge_ids[scope.identifiers[0]])))
        if not identifiers:
            raise ValueError('This junction has no connected roads')
        if len(identifiers) > MAX_AREA_SAMPLES:
            raise ValueError('This junction has too many approaches; select a smaller road area')
        return identifiers
    if scope.kind != 'area':
        raise ValueError('Unknown analysis scope')
    if len(scope.identifiers) > MAX_AREA_ROADS:
        raise ValueError(f'Select at most {MAX_AREA_ROADS} connected roads for one area')
    if not connected_roads(network, scope.identifiers):
        raise ValueError('Area roads must connect through shared junctions')
    return tuple(sorted(set(scope.identifiers)))


def selection_roads(network, selection):
    if selection is None:
        return frozenset()
    kind, identifier = selection
    if kind == 'road':
        return frozenset((identifier,))
    if kind == 'node':
        return frozenset(network.edge_ids[identifier])
    return frozenset(identifier)


def selection_target(selection):
    if not selection:
        return None
    kind, identifier = selection
    return identifier if kind == 'road' else AnalysisScope.junction(identifier) if kind == 'node' else AnalysisScope.area(identifier)


def scope_label(network, scope):
    if isinstance(scope, str):
        return scope
    if scope.kind == 'junction':
        return f'Junction {network.nodes_by_id[scope.identifiers[0]]["number"]} / {len(scope_roads(network, scope))} approaches'
    return f'Connected area / {len(scope.identifiers)} roads'


def area_context(network, scope):
    identifiers = scope_roads(network, scope)
    roads = [network.roads_by_id[identifier] for identifier in identifiers]
    node_ids = sorted({road.properties[key] for road in roads for key in ('source', 'target')})
    outside = sorted({edge for node in node_ids for edge in network.edge_ids[node]} - set(identifiers))
    boundary = [node for node in node_ids if set(network.edge_ids[node]) - set(identifiers)]
    junctions = []
    labels = {}
    for node_id in node_ids:
        node = network.nodes_by_id[node_id]
        label = f'Junction {node["number"]}'
        labels[node_id] = label
        junctions.append({'id': node_id, 'label': label, 'degree': node['degree'],
                          'coordinate_lon_lat': node['coordinate'],
                          'connected_edge_ids': list(network.edge_ids[node_id]),
                          'scope_role': 'boundary' if node_id in boundary else 'internal'})
    central = network.nodes_by_id[scope.identifiers[0]] if scope.kind == 'junction' else None
    samples = []
    sampled_outside = outside[:max(0, MAX_AREA_SAMPLES-len(roads))]
    for index, identifier in enumerate((*identifiers, *sampled_outside)):
        road = network.roads_by_id[identifier]
        touches = [node for node in node_ids if identifier in network.edge_ids[node]]
        selected = identifier in identifiers
        samples.append({'label': f'{"Approach" if central else "Area road"} {index+1}' if selected else f'Boundary approach {index-len(roads)+1}',
                        'edge_id': identifier, 'junctions': [labels[node] for node in touches],
                        'road': road, 'node_point': central['point'] if central and selected else (
                            network.nodes_by_id[touches[0]]['point'] if not selected else None),
                        'scope_role': 'selected' if selected else 'boundary_approach'})
    selected_area = {'type': scope.kind, 'label': scope_label(network, scope),
                     'edge_ids': list(identifiers), 'node_ids': node_ids,
                     'road_count': len(roads), 'node_count': len(node_ids),
                     'total_length_m': round(sum(road.properties['length_m'] for road in roads), 2),
                     'boundary_node_ids': boundary, 'boundary_approach_edge_ids': outside}
    if central:
        selected_area['selected_junction_id'] = central['id']
    return {'selected_area': selected_area, 'selected_roads': [road_details(road) for road in roads],
            'junctions': junctions, 'samples': samples,
            'coverage': {'selected_roads': len(roads), 'sampled_boundary_approaches': len(sampled_outside),
                         'omitted_boundary_edge_ids': outside[len(sampled_outside):],
                         'sample_limit': MAX_AREA_SAMPLES,
                         'note': 'Each graph edge is sampled once. Provider fragments may overlap; do not sum fragment times or infer area vehicle counts.'}}
