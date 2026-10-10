"""Deterministic connectivity facts for an inferred, undirected road graph."""
from collections import defaultdict
import heapq
import math

from .live_traffic import check_cancel, road_context


def adjacency(network):
    neighbours = defaultdict(list)
    for road in network.roads:
        source, target = road.properties['source'], road.properties['target']
        length = road.properties['length_m']
        if isinstance(length, bool) or not isinstance(length, (int, float)) or not math.isfinite(length) or length < 0:
            continue
        neighbours[source].append((target, road.id, length))
        neighbours[target].append((source, road.id, length))
    return neighbours


def alternative_path(neighbours, source, target, excluded_edge, cancel):
    """Shortest graph-length connection with one edge removed, not a road route."""
    distances, previous = {source: 0}, {}
    queue = [(0, source)]
    while queue:
        check_cancel(cancel)
        distance, node = heapq.heappop(queue)
        if distance != distances.get(node):
            continue
        if node == target:
            edge_ids = []
            while node != source:
                node, edge_id = previous[node]
                edge_ids.append(edge_id)
            return {'status': 'connected', 'length_m': round(distance, 2),
                    'edge_ids': list(reversed(edge_ids))}
        for other, edge_id, length in neighbours[node]:
            if edge_id == excluded_edge:
                continue
            updated = distance + length
            if updated < distances.get(other, math.inf):
                distances[other] = updated
                previous[other] = (node, edge_id)
                heapq.heappush(queue, (updated, other))
    return {'status': 'disconnected_in_dataset', 'length_m': None, 'edge_ids': []}


def junction_components(neighbours, removed, cancel):
    """Group a junction's neighbours by connectivity after that node is removed."""
    pending = {node for node, _, _ in neighbours[removed] if node != removed}
    groups = []
    while pending:
        seed = min(pending)
        visited, queue = {seed}, [seed]
        while queue:
            check_cancel(cancel)
            node = queue.pop()
            for other, _, _ in neighbours[node]:
                if other != removed and other not in visited:
                    visited.add(other)
                    queue.append(other)
        group = pending & visited
        groups.append(sorted(group))
        pending -= group
    return {'is_articulation_in_dataset': len(groups) > 1,
            'neighbour_component_count_after_removal': len(groups), 'neighbour_groups': groups}


def network_facts(network, road_id, cancel):
    context = road_context(network, road_id)
    samples = context.pop('samples')
    neighbours = adjacency(network)
    selected = context['selected_road']
    alternative = alternative_path(neighbours, selected['source'], selected['target'], road_id, cancel)
    alternative['selected_edge_is_bridge_in_dataset'] = alternative['status'] == 'disconnected_in_dataset'
    alternative['interpretation'] = 'Undirected graph connectivity only; this is not a verified drivable diversion or traffic forecast.'
    junctions = [{**node, **junction_components(neighbours, node['id'], cancel)}
                 for node in context['junctions']]
    return {**context, 'junctions': junctions, 'alternative_connection_without_selected_edge': alternative,
            'connected_roads': [{key: item[key] for key in ('edge_id', 'label', 'junctions')} |
                                {'length_m': item['road'].properties['length_m']} for item in samples],
            'graph_assumptions': 'KML graph is undirected; junctions inferred from shared coordinates; legal turns and one-way restrictions unknown.',
            'unavailable_design_data': ['lane counts', 'verified carriageway widths', 'signal phases/timings',
                                        'turning movements', 'pedestrian counts', 'bus operations',
                                        'parking/loading activity', 'measured historical traffic', 'implementation costs']}
