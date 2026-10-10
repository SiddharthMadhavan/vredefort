"""Road-network accessibility estimates, not dispatch or service guarantees.

Facilities attach to the nearest road within 250m. Their projection seeds both
endpoints with fractional edge travel time. Multi-source Dijkstra then finds
the fastest mapped facility for every graph node. Baseline uses the same hour
without closures; closures and diverted traffic use the scenario's link speeds.
Off-road connectors, dispatch, availability and legal turn restrictions are
unknown and deliberately excluded from these road-only travel estimates.
"""
from concurrent.futures import CancelledError
from dataclasses import dataclass
import heapq
import math


SERVICES = ('fire', 'hospitals')
SERVICE_NAMES = {'fire': 'Fire station', 'hospitals': 'Hospital access'}
COLORS = {'lost': '#ff6474', 'delayed': '#ff9959', 'degraded': '#f5d26d',
          'gap': '#ba95f4', 'normal': '#65d994'}
STATUS_NAMES = {'lost': 'Lost mapped access', 'delayed': 'Slow access',
                'degraded': 'Added delay', 'gap': 'Existing coverage gap', 'normal': 'Within threshold'}


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError('Emergency analysis superseded')


@dataclass(frozen=True, slots=True)
class FacilityAnchor:
    kind: str
    index: int
    name: str
    edge_id: str
    fraction: float
    distance_m: float
    point: tuple
    provenance: str


@dataclass(frozen=True, slots=True)
class AccessPoint:
    node_id: str
    number: int
    point: tuple
    kind: str
    seconds: float
    baseline_seconds: float
    facility: FacilityAnchor | None
    baseline_facility: FacilityAnchor | None
    status: str

    @property
    def added_seconds(self):
        return max(0., self.seconds - self.baseline_seconds) if math.isfinite(self.baseline_seconds) else None


def risk_order(point):
    rank = {'lost': 4, 'degraded': 3, 'delayed': 2, 'gap': 1, 'normal': 0}
    return (-rank[point.status], -point.seconds, -(point.added_seconds or 0), point.number, point.kind)


@dataclass(frozen=True, slots=True)
class RouteLeg:
    edge_id: str
    start_fraction: float
    end_fraction: float


@dataclass(frozen=True, slots=True)
class EmergencyRoute:
    facility: FacilityAnchor
    node_id: str
    point: tuple
    legs: tuple[RouteLeg, ...]
    seconds: float

    @property
    def edge_ids(self):
        return tuple(leg.edge_id for leg in self.legs)


@dataclass(frozen=True, slots=True)
class EmergencyReport:
    hour: int
    points: tuple[AccessPoint, ...]
    anchors: tuple[FacilityAnchor, ...]
    skipped: tuple[tuple[str, str], ...]
    threshold_s: float
    added_threshold_s: float
    paths: dict

    def risks(self, kind=None):
        return tuple(sorted((p for p in self.points if p.status != 'normal' and
                             (kind is None or p.kind == kind)), key=risk_order))

    def route(self, point):
        """Reconstruct only the selected path, retaining fractional facility access."""
        if point.facility is None or not math.isfinite(point.seconds):
            return None
        parents = self.paths[point.kind]
        legs, node = [], point.node_id
        while node is not None:
            parent, leg = parents[node]
            if leg.start_fraction != leg.end_fraction:
                legs.append(leg)
            node = parent
        return EmergencyRoute(point.facility, point.node_id, point.point, tuple(reversed(legs)), point.seconds)


def road_projection(point, road):
    """Squared snap distance and fraction along a source-to-target polyline."""
    segments = [(a, b, math.dist(a, b)) for path in road.paths for a, b in zip(path, path[1:])]
    length = sum(s[2] for s in segments)
    best, fraction, travelled = math.inf, 0., 0.
    for a, b, segment_length in segments:
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = max(0., min(1., ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) /
                         (segment_length ** 2))) if segment_length else 0.
        distance = (point[0] - a[0] - t * dx) ** 2 + (point[1] - a[1] - t * dy) ** 2
        if distance < best:
            best = distance
            fraction = (travelled + t * segment_length) / length if length else 0.
        travelled += segment_length
    return best, fraction


class EmergencyAccessModel:
    def __init__(self, model, datasets, snap_radius_m=250., cancel=None):
        self.model = model
        self.nodes = tuple(datasets['graph']['nodes'])
        nodes_by_id = {n['id']: n for n in self.nodes}
        view = datasets['views']['KML road graph']
        self.anchors, self.skipped = [], []
        for kind in SERVICES:
            for index, facility in enumerate(datasets[kind]):
                check_cancel(cancel)
                name = str(facility.get('FIRE_STAName') or facility.get('Name') or 'Unnamed facility')
                point = tuple(facility['point'])
                metres = 2 * math.pi * 6371008.8 * math.cos(math.radians(facility['coordinate'][1]))
                radius = snap_radius_m / metres
                candidates = view['index'].query((point[0] - radius, point[1] - radius,
                                                  point[0] + radius, point[1] + radius))
                closest = None
                for road_index in sorted(candidates):
                    road = view['roads'][road_index]
                    if road.id not in model.by_id:
                        continue
                    distance, fraction = road_projection(point, road)
                    if closest is None or distance < closest[0]:
                        closest = distance, fraction, road
                if closest is None or math.sqrt(closest[0]) * metres > snap_radius_m:
                    self.skipped.append((kind, name))
                    continue
                distance, fraction, road = closest
                # Dataset geometries normally run source -> target. Verify this
                # using actual node coordinates rather than trusting file order.
                source = nodes_by_id.get(road.properties['source'])
                if source and math.dist(road.paths[0][0], source['point']) > math.dist(road.paths[-1][-1], source['point']):
                    fraction = 1 - fraction
                self.anchors.append(FacilityAnchor(kind, index, name, road.id, fraction,
                    math.sqrt(distance) * metres, point,
                    str(facility.get('match_status') or facility.get('coordinate_source') or 'Supplied dataset')))
        self.anchors, self.skipped = tuple(self.anchors), tuple(self.skipped)
        self.baseline_cache = None

    def access(self, result, kind, cancel=None):
        costs = [edge['length_m'] / (result.links[edge['id']].speed / 3.6)
                 if not result.links[edge['id']].closed and result.links[edge['id']].speed > 0
                 else math.inf for edge in self.model.edges]
        distances, facilities, parents, heap = {}, {}, {}, []
        for anchor_index, anchor in enumerate(self.anchors):
            if anchor.kind != kind:
                continue
            edge_index = self.model.by_id[anchor.edge_id]
            cost, edge = costs[edge_index], self.model.edges[edge_index]
            if not math.isfinite(cost):
                continue
            for node, fraction, endpoint in ((edge['source'], anchor.fraction, 0.),
                                              (edge['target'], 1 - anchor.fraction, 1.)):
                distance = cost * fraction
                if node not in result.blocked_nodes and distance < distances.get(node, math.inf):
                    distances[node], facilities[node] = distance, anchor_index
                    parents[node] = None, RouteLeg(anchor.edge_id, anchor.fraction, endpoint)
                    heapq.heappush(heap, (distance, node, anchor_index))
        while heap:
            check_cancel(cancel)
            distance, node, anchor_index = heapq.heappop(heap)
            if distance != distances[node] or facilities[node] != anchor_index:
                continue
            for target, edge_index in self.model.adjacency.get(node, ()):
                if target in result.blocked_nodes:
                    continue
                candidate = distance + costs[edge_index]
                if candidate < distances.get(target, math.inf):
                    distances[target], facilities[target] = candidate, anchor_index
                    edge = self.model.edges[edge_index]
                    forward = node == edge['source']
                    parents[target] = node, RouteLeg(edge['id'], 0. if forward else 1., 1. if forward else 0.)
                    heapq.heappush(heap, (candidate, target, anchor_index))
        return distances, facilities, parents

    def analyze(self, baseline, scenario, threshold_s=600., added_threshold_s=180., cancel=None):
        if baseline.hour != scenario.hour or baseline.blocked_nodes or any(x.closed for x in baseline.links.values()):
            raise ValueError('Emergency baseline must be the same hour without closures')
        if threshold_s <= 0 or added_threshold_s <= 0:
            raise ValueError('Analysis thresholds must be positive')
        check_cancel(cancel)
        if self.baseline_cache is None or self.baseline_cache[0] is not baseline:
            values = {kind: self.access(baseline, kind, cancel) for kind in SERVICES}
            self.baseline_cache = baseline, values
        points, paths = [], {}
        for kind in SERVICES:
            before, before_facilities, before_paths = self.baseline_cache[1][kind]
            after, after_facilities, paths[kind] = (before, before_facilities, before_paths) if scenario is baseline else self.access(scenario, kind, cancel)
            for node in self.nodes:
                check_cancel(cancel)
                identifier = node['id']
                seconds, baseline_seconds = after.get(identifier, math.inf), before.get(identifier, math.inf)
                if not math.isfinite(seconds):
                    status = 'lost' if math.isfinite(baseline_seconds) else 'gap'
                elif math.isfinite(baseline_seconds) and seconds - baseline_seconds >= added_threshold_s:
                    status = 'degraded'
                elif seconds > threshold_s:
                    status = 'delayed'
                else:
                    status = 'normal'
                anchor = self.anchors[after_facilities[identifier]] if identifier in after_facilities else None
                old_anchor = self.anchors[before_facilities[identifier]] if identifier in before_facilities else None
                points.append(AccessPoint(identifier, node['number'], tuple(node['point']), kind,
                                          seconds, baseline_seconds, anchor, old_anchor, status))
        return EmergencyReport(scenario.hour, tuple(points), self.anchors, self.skipped, threshold_s, added_threshold_s, paths)
