"""Hourly link-flow replay and conditional, capacity-aware closure assignment.

This is a quasi-static incident model, not a calibrated citywide OD model.
See data/traffic-model.txt for equations, units and explicit demand assumptions.
"""
from array import array
from concurrent.futures import CancelledError
from dataclasses import dataclass
import gzip
import heapq
import json
import math
from pathlib import Path
import sys

FIELDS = ('Traffic Volume', 'Average Speed', 'Travel Time Index',
          'Congestion Level', 'Road Capacity Utilization')


class TrafficDataset:
    def __init__(self, metadata, values):
        self.metadata, self.values = metadata, values
        self.hours = tuple(metadata['hours'])
        self.edge_ids = tuple(metadata['edge_ids'])
        self.edge_index = {identifier: i for i, identifier in enumerate(self.edge_ids)}
        self.capacities = tuple(metadata['capacities_veh_h'])
        self.count = len(self.edge_ids)
        if len(values) != len(self.hours) * self.count * len(FIELDS):
            raise ValueError('Traffic cache size does not match its metadata; re-import CSV')

    @classmethod
    def load(cls, folder):
        folder = Path(folder)
        metadata = json.loads((folder / 'bengaluru-traffic.metadata.json').read_text(encoding='utf-8'))
        if metadata['format'] != 'float32-le-hour-edge-5-v1' or metadata['fields'] != list(FIELDS):
            raise ValueError('Unsupported traffic cache format')
        values = array('f')
        with gzip.open(folder / 'bengaluru-traffic.bin.gz', 'rb') as stream:
            values.frombytes(stream.read())
        if sys.byteorder != 'little':
            values.byteswap()
        return cls(metadata, values)

    def hour(self, index):
        if not 0 <= index < len(self.hours):
            raise ValueError('Hour is outside the supplied dataset')
        start = index * self.count * len(FIELDS)
        return [tuple(self.values[start + i * 5:start + i * 5 + 5]) for i in range(self.count)]


@dataclass(frozen=True, slots=True)
class LinkState:
    baseline: float
    flow: float
    capacity: float
    speed: float
    congestion: float  # fraction 0..1
    delay_ratio: float
    closed: bool = False


@dataclass(frozen=True, slots=True)
class TrafficResult:
    hour: int
    links: dict
    blocked_nodes: frozenset
    affected_demand: float
    rerouted_demand: float
    unmet_demand: float
    relative_gap: float
    iterations: int
    converged: bool


class TrafficModel:
    ALPHA, BETA = .15, 4

    def __init__(self, graph, dataset):
        self.dataset = dataset
        self.edges = tuple(graph['edges'])
        self.by_id = {edge['id']: i for i, edge in enumerate(self.edges)}
        self.nodes = {node['id'] for node in graph['nodes']}
        if set(self.by_id) != set(dataset.edge_ids):
            raise ValueError('Traffic edge IDs do not match the KML graph')
        self.adjacency = {node: [] for node in self.nodes}
        for i, edge in enumerate(self.edges):
            if edge['length_m'] <= 0:
                raise ValueError('Traffic requires positive road lengths')
            self.adjacency[edge['source']].append((edge['target'], i))
            self.adjacency[edge['target']].append((edge['source'], i))

    def shortest_paths(self, origin, costs, closed, destinations):
        """One Dijkstra per origin, preserving parallel edge identities."""
        distances, parents, heap = {origin: 0.0}, {}, [(0.0, origin)]
        remaining = set(destinations)
        while heap and remaining:
            distance, node = heapq.heappop(heap)
            if distance > distances[node]:
                continue
            remaining.discard(node)
            for target, index in self.adjacency[node]:
                if index in closed:
                    continue
                candidate = distance + costs[index]
                if candidate < distances.get(target, math.inf):
                    distances[target] = candidate
                    parents[target] = node, index
                    heapq.heappush(heap, (candidate, target))
        paths = {}
        for destination in destinations:
            if destination not in distances:
                continue
            node, path = destination, []
            while node != origin:
                node, edge = parents[node]
                path.append(edge)
            paths[destination] = tuple(reversed(path))
        return paths

    def closure_demand(self, baseline, blocked_edges, blocked_nodes):
        """Road trips retain endpoints; junction trips join surviving approaches.

        For a closed-node cluster with k boundary neighbours and loads b_i,
        d_ij=min(b_i,b_j)/(k-1). Each boundary load is used at most once.
        Unpaired load / 2 is demand with an inaccessible endpoint. Internal
        link counts are not counted again as trips crossing the same cluster.
        """
        closed = {i for i, e in enumerate(self.edges)
                  if e['id'] in blocked_edges or e['source'] in blocked_nodes or e['target'] in blocked_nodes}
        demands, endpoint_unmet = {}, 0.0

        def add(a, b, flow):
            if a != b and flow > 0:
                pair = tuple(sorted((a, b)))
                demands[pair] = demands.get(pair, 0.0) + flow

        for identifier in sorted(blocked_edges):
            index = self.by_id[identifier]
            edge = self.edges[index]
            if edge['source'] not in blocked_nodes and edge['target'] not in blocked_nodes:
                if edge['source'] == edge['target']:
                    # A zero-length endpoint route would silently erase loop trips.
                    # Their actual destination along the loop is not in this dataset.
                    endpoint_unmet += baseline[index]
                else:
                    add(edge['source'], edge['target'], baseline[index])
        remaining = set(blocked_nodes)
        while remaining:
            cluster, stack = set(), [min(remaining)]
            while stack:
                node = stack.pop()
                if node in cluster:
                    continue
                cluster.add(node)
                remaining.discard(node)
                stack.extend(target for target, _ in self.adjacency[node]
                             if target in blocked_nodes and target not in cluster)
            boundary = {}
            for node in cluster:
                for target, index in self.adjacency[node]:
                    if target not in cluster:
                        boundary[target] = boundary.get(target, 0.0) + baseline[index]
            ports = sorted(boundary.items())
            assigned = 0.0
            if len(ports) > 1:
                for i, (a, qa) in enumerate(ports):
                    for b, qb in ports[i + 1:]:
                        demand = min(qa, qb) / (len(ports) - 1)
                        add(a, b, demand)
                        assigned += demand
            endpoint_unmet += max(0.0, sum(boundary.values()) / 2 - assigned)
        return closed, demands, endpoint_unmet

    def solve(self, hour, blocked_edges=frozenset(), blocked_nodes=frozenset(),
              max_iterations=60, tolerance=.01, cancel_event=None):
        def checkpoint():
            if cancel_event is not None and cancel_event.is_set():
                raise CancelledError('Scenario superseded or app closed')

        checkpoint()
        blocked_edges, blocked_nodes = frozenset(blocked_edges), frozenset(blocked_nodes)
        if not blocked_edges <= self.by_id.keys() or not blocked_nodes <= self.nodes:
            raise ValueError('Unknown road or junction ID')
        if max_iterations < 1 or not math.isfinite(tolerance) or tolerance <= 0:
            raise ValueError('Invalid assignment iteration limit or tolerance')
        rows = self.dataset.hour(hour)
        rows = [rows[self.dataset.edge_index[e['id']]] for e in self.edges]
        baseline = [r[0] for r in rows]
        capacities = [self.dataset.capacities[self.dataset.edge_index[e['id']]] for e in self.edges]
        observed_times = [e['length_m'] / (r[1] / 3.6) for e, r in zip(self.edges, rows)]
        closed, demands, endpoint_unmet = self.closure_demand(baseline, blocked_edges, blocked_nodes)
        background = [0.0 if i in closed else q for i, q in enumerate(baseline)]
        normalization = [1 + self.ALPHA * (q / c) ** self.BETA for q, c in zip(baseline, capacities)]

        def costs(extra):
            return [t * (1 + self.ALPHA * ((b + x) / c) ** self.BETA) / n
                    for t, b, x, c, n in zip(observed_times, background, extra, capacities, normalization)]

        grouped = {}
        for (a, b), q in demands.items():
            grouped.setdefault(a, {})[b] = q

        def assign(times):
            extra, routed, unmet, shortest_total = [0.0] * len(self.edges), 0.0, endpoint_unmet, 0.0
            for origin, destinations in grouped.items():
                checkpoint()
                paths = self.shortest_paths(origin, times, closed, destinations)
                for destination, demand in destinations.items():
                    if destination not in paths:
                        unmet += demand
                        continue
                    path = paths[destination]
                    routed += demand
                    shortest_total += demand * sum(times[index] for index in path)
                    for index in path:
                        extra[index] += demand
            return extra, routed, unmet, shortest_total

        extra, routed, unmet, _ = assign(observed_times)
        gap, iterations = 0.0, 0
        if routed:
            for iteration in range(1, max_iterations + 1):
                checkpoint()
                times = costs(extra)
                target, _, _, shortest = assign(times)
                current = sum(x * t for x, t in zip(extra, times))
                gap = max(0.0, (current - shortest) / current) if current else 0.0
                iterations = iteration
                if gap <= tolerance or iteration == max_iterations:
                    break
                weight = 1 / (iteration + 1)
                extra = [x + weight * (y - x) for x, y in zip(extra, target)]
        times = costs(extra)
        links = {}
        for i, (edge, row, capacity, time) in enumerate(zip(self.edges, rows, capacities, times)):
            is_closed = i in closed
            ratio = time / observed_times[i]
            severity = max(0.0, min(1.0, 1 - (1 - row[3] / 100) / max(1.0, ratio)))
            links[edge['id']] = LinkState(row[0], background[i] + extra[i], capacity,
                                         0.0 if is_closed else row[1] / ratio,
                                         severity, ratio, is_closed)
        return TrafficResult(hour, links, blocked_nodes, sum(demands.values()) + endpoint_unmet,
                             routed, unmet, gap, iterations, gap <= tolerance)
