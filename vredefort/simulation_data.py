"""Load the old simulation inputs against the current explorer's exact graph."""
from .data import DATA, read_points
from .explore_map import load_network
from .traffic import TrafficDataset, TrafficModel


def load_simulation_data(network=None):
    network = network or load_network()
    view = {'roads': network.roads, 'index': network.road_index,
            'nodes': network.nodes, 'by_id': network.roads_by_id}
    graph = {'nodes': network.nodes, 'edges': [road.properties for road in network.roads]}
    datasets = {'graph': graph, 'views': {'KML road graph': view},
                'hospitals': read_points('bengaluru-hospitals.geojson')[0],
                'fire': read_points('bengaluru-fire-stations.geojson')[0]}
    return datasets, TrafficModel(graph, TrafficDataset.load(DATA))
