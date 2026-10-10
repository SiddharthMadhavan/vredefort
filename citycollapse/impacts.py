"""Closure impacts: actual link changes, feasible routes, and facility proximity.

Facility proximity is an access-risk flag; no facility failure is inferred.
"""
from concurrent.futures import CancelledError
from dataclasses import dataclass
import math
from .geometry import line_distance_squared
from .traffic import AssignedRoute


@dataclass(frozen=True, slots=True)
class NearbyFacility:
    kind: str
    index: int
    name: str
    distance_m: float
    road_ids: tuple
    near_closed: bool
    facility_type: str = ''
    facility_category: str = ''


@dataclass(frozen=True, slots=True)
class Diversion:
    closure_id: str | None
    route: AssignedRoute
    assigned: bool = False


@dataclass(frozen=True, slots=True)
class ImpactReport:
    closed_roads: frozenset
    loaded_roads: frozenset
    affected_nodes: frozenset
    facilities: tuple
    diversions: tuple
    unavailable: tuple
    radius_m: float

    @property
    def affected_roads(self):
        return self.closed_roads | self.loaded_roads


def nearby_facilities(view, facilities, closed, loaded, radius_m=250):
    affected = closed | loaded
    items = []
    for kind in ('hospitals', 'fire'):
        for index, facility in enumerate(facilities[kind]):
            point = facility['point']
            # Local scale for normalized Web Mercator; suitable for a 250m buffer.
            metres_per_world = 2 * math.pi * 6371008.8 * math.cos(math.radians(facility['coordinate'][1]))
            radius = radius_m / metres_per_world
            box = (point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius)
            matches = []
            for road_index in view['index'].query(box):
                road = view['roads'][road_index]
                if road.id not in affected:
                    continue
                distance = math.sqrt(min(line_distance_squared(*point, path) for path in road.paths)) * metres_per_world
                if distance <= radius_m:
                    matches.append((distance, road.id))
            if matches:
                matches.sort()
                name = facility.get('Name') if kind == 'hospitals' else facility.get('FIRE_STAName')
                items.append(NearbyFacility(kind, index, name or 'Unnamed facility', matches[0][0],
                                             tuple(identifier for _, identifier in matches),
                                             any(identifier in closed for _, identifier in matches),
                                             str(facility.get('Type') or ('Hospital' if kind == 'hospitals' else 'Fire station')),
                                             str(facility.get('facility_category') or '')))
    return tuple(sorted(items, key=lambda f: (not f.near_closed, f.distance_m, f.kind, f.index)))


def build_impact_report(model, result, datasets, blocked_edges, cancel_event=None, radius_m=250):
    closed = frozenset(key for key, state in result.links.items() if state.closed)
    loaded = frozenset(key for key, state in result.links.items()
                       if not state.closed and state.flow - state.baseline > max(1e-6, state.baseline * 1e-9))
    affected = closed | loaded
    nodes = frozenset(node for edge in model.edges if edge['id'] in affected
                      for node in (edge['source'], edge['target']))
    facilities = nearby_facilities(datasets['views']['KML road graph'], datasets, closed, loaded, radius_m)
    diversions, unavailable = [], []
    for identifier in sorted(blocked_edges):
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError('Impact report superseded')
        routes = model.diversion_paths(identifier, result, cancel_event=cancel_event)
        if not routes:
            edge = model.edges[model.by_id[identifier]]
            reason = ('Loop trip destination is unknown' if edge['source'] == edge['target'] else
                      'Endpoint junction is blocked' if edge['source'] in result.blocked_nodes or edge['target'] in result.blocked_nodes else
                      'No connected detour in this graph')
            unavailable.append((identifier, reason))
        for route in routes:
            diversions.append(Diversion(identifier, route))
    # Junctions have several approach-to-approach trips; show all routes actually
    # used by the assignment, with their allocated flow (not invented previews).
    if result.blocked_nodes:
        diversions.extend(Diversion(None, route, True) for route in result.routes)
    return ImpactReport(closed, loaded, nodes, facilities, tuple(diversions), tuple(unavailable), radius_m)
