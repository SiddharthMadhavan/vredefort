"""Regenerate a graph from local line data without JavaScript or API requests."""
import argparse
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from citycollapse.graph_builder import build_graph

parser = argparse.ArgumentParser()
parser.add_argument('input', type=Path)
parser.add_argument('--name', default='bengaluru-kml-road')
parser.add_argument('--exact', action='store_true', help='Use exact KML coordinates instead of legacy five-decimal OSM keys')
args = parser.parse_args()
if Path(args.name).name != args.name:
    parser.error('Name must be a filename prefix, not a path')
graph = build_graph(json.loads(args.input.read_text(encoding='utf-8')), exact=args.exact)
folder = Path(__file__).resolve().parent.parent / 'data'
(folder / f'{args.name}-graph.json').write_text(json.dumps(graph), encoding='utf-8')
for kind in ['nodes', 'edges']:
    features = []
    for record in graph[kind]:
        properties = dict(record)
        if kind == 'nodes':
            coordinates = [properties.pop('lon'), properties.pop('lat')]
            properties.pop('edge_ids')
        else:
            coordinates = properties.pop('coordinates')
        features.append({'type': 'Feature', 'id': properties['id'], 'properties': properties, 'geometry': {'type': 'Point' if kind == 'nodes' else 'LineString', 'coordinates': coordinates}})
    (folder / f'{args.name}-{kind}.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': features}), encoding='utf-8')
print(f'{len(graph["nodes"])} nodes, {len(graph["edges"])} edges. Shared-vertex topology; degree-two continuations removed.')
metadata = {
    'generatedAt': datetime.now(timezone.utc).isoformat(),
    'input': str(args.input), 'inputSha256': hashlib.sha256(args.input.read_bytes()).hexdigest(),
    'nodeCount': len(graph['nodes']), 'edgeCount': len(graph['edges']),
    'topology': 'Undirected shared-vertex graph, with degree-two continuation nodes contracted. No proximity snapping or geometric-crossing junctions inferred.',
    'coordinateKeys': 'Exact KML coordinates' if args.exact else 'Legacy five-decimal OSM coordinate keys',
    'numbering': '1-based, sorted by longitude then latitude; IDs reference coordinate keys.',
    'lengths': 'Haversine sum in metres, rounded to three decimals.',
    'limitations': ['No one-way directions or turn restrictions inferred.', 'Junction candidates are not verified physical junctions. Bridge/tunnel connectivity is unavailable.'],
}
(folder / f'{args.name}-graph.metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
