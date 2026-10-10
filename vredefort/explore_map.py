"""Road exploration: one local graph, spatial selection, and map painting."""
from dataclasses import dataclass

from PIL import Image, ImageDraw

from .data import Road, SpatialIndex, read_points, read_roads
from .geometry import line_distance_squared


@dataclass(frozen=True)
class RoadNetwork:
    roads: list[Road]
    road_index: SpatialIndex
    nodes: list[dict]
    node_index: SpatialIndex
    roads_by_id: dict[str, Road]
    nodes_by_id: dict[str, dict]
    edge_ids: dict[str, list[str]]


def load_network():
    """Load only the road/node files; no traffic or infrastructure datasets."""
    roads, road_index = read_roads('bengaluru-kml-road-edges.geojson')
    nodes, node_index = read_points('bengaluru-kml-road-nodes.geojson')
    edge_ids = {node['id']: [] for node in nodes}
    for road in roads:
        for identifier in set((road.properties['source'], road.properties['target'])):
            if identifier not in edge_ids:
                raise ValueError(f'Road {road.id} references a missing node')
            edge_ids[identifier].append(road.id)
    return RoadNetwork(roads, road_index, nodes, node_index,
                       {road.id: road for road in roads},
                       {node['id']: node for node in nodes}, edge_ids)


def nearest_node(network, camera, x, y):
    # Smaller targets at city scale keep nearby road segments selectable.
    radius = 7 if camera.zoom >= 13 else 4
    box = (*camera.world(x - radius, y - radius),
           *camera.world(x + radius, y + radius))
    nearest, distance = None, radius ** 2
    for index in sorted(network.node_index.query(box)):
        node = network.nodes[index]
        sx, sy = camera.screen(node['point'])
        squared = (x - sx) ** 2 + (y - sy) ** 2
        if squared <= distance:
            nearest, distance = node, squared
    return nearest


def nearest_road(network, camera, x, y):
    radius = 7
    box = (*camera.world(x - radius, y - radius),
           *camera.world(x + radius, y + radius))
    nearest, distance = None, radius ** 2
    for index in sorted(network.road_index.query(box)):
        road = network.roads[index]
        squared = min(line_distance_squared(x, y, camera.screen_path(path))
                      for path in road.paths)
        if squared <= distance:
            nearest, distance = road, squared
    return nearest


def _paint_base(camera, tiles, network):
    image = Image.new('RGB', (camera.width, camera.height), '#0b100d')
    draw = ImageDraw.Draw(image)
    for z, x, y in camera.tile_keys():
        sx, sy = camera.screen((x / 2 ** z, y / 2 ** z))
        tile = tiles.get((z, x, y))
        if tile is None:
            draw.rectangle((sx, sy, sx + 255, sy + 255), outline='#18251d')
        else:
            image.paste(tile, (round(sx), round(sy)))
    if network is None:
        return image

    width = max(1, min(4, round(1 + (camera.zoom - 11) * .4)))

    for index in sorted(network.road_index.query(camera.bounds)):
        for path in network.roads[index].paths:
            draw.line(camera.screen_path(path), fill='#71877a', width=width, joint='curve')

    if camera.zoom >= 13:
        for index in sorted(network.node_index.query(camera.bounds)):
            x, y = camera.screen(network.nodes[index]['point'])
            draw.ellipse((x - 2, y - 2, x + 2, y + 2),
                         fill='#a1bfaa', outline='#18291d')
    return image


class ExplorePainter:
    """Reuse the background bitmap while selections and traffic change.

    Owned by one paint worker. The retained image is never modified by callers.
    Tile object identities invalidate it when actual visible tiles are replaced.
    """
    def __init__(self):
        self.key = self.base = None
        self.tiles, self.network = {}, None

    def paint(self, camera, tiles, network, selection):
        key = camera, id(network), tuple(sorted((key, id(tile)) for key, tile in tiles.items()))
        if key != self.key:
            self.base = _paint_base(camera, tiles, network)
            self.key = key
            self.tiles, self.network = dict(tiles), network
        image = self.base.copy()
        if network is not None and selection:
            _paint_selection(image, camera, network, selection)
        return image


def _paint_selection(image, camera, network, selection):
    draw = ImageDraw.Draw(image)
    width = max(1, min(4, round(1 + (camera.zoom - 11) * .4)))

    def road_line(road, color, thickness):
        for path in road.paths:
            draw.line(camera.screen_path(path), fill=color, width=thickness, joint='curve')

    if selection:
        kind, identifier = selection
        if kind == 'road':
            road = network.roads_by_id[identifier]
            road_line(road, '#173a28', width + 5)
            road_line(road, '#8ae8a9', width + 2)
            endpoints = (network.nodes_by_id[road.properties['source']],
                         network.nodes_by_id[road.properties['target']])
        elif kind == 'node':
            for edge_id in network.edge_ids[identifier]:
                road_line(network.roads_by_id[edge_id], '#8ae8a9', width + 1)
            endpoints = (network.nodes_by_id[identifier],)
        else:
            node_ids = set()
            for edge_id in identifier:
                road = network.roads_by_id[edge_id]
                road_line(road, '#173a28', width + 5)
                road_line(road, '#8ae8a9', width + 2)
                node_ids.update((road.properties['source'], road.properties['target']))
            endpoints = tuple(network.nodes_by_id[node] for node in sorted(node_ids))
        for node in endpoints:
            x, y = camera.screen(node['point'])
            draw.ellipse((x - 5, y - 5, x + 5, y + 5),
                         fill='#8ae8a9', outline='#e0ffe9', width=2)


def paint_explore(camera, tiles, network, selection):
    """One-shot renderer; long-lived windows use their own ExplorePainter."""
    return ExplorePainter().paint(camera, tiles, network, selection)
