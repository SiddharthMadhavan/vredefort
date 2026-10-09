import argparse
import hashlib
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('input', type=Path)
args = parser.parse_args()
ns = {'k': 'http://www.opengis.net/kml/2.2'}
features = []
for index, placemark in enumerate(ET.parse(args.input).findall('.//k:Placemark', ns)):
    properties = {item.attrib['name']: item.text or '' for item in placemark.findall('.//k:SimpleData', ns)}
    point = placemark.find('k:Point/k:coordinates', ns)
    if point is None or not point.text:
        raise ValueError(f'Placemark {index + 1} has no point coordinate')
    coordinates = [float(value) for value in point.text.strip().split(',')[:2]]
    if len(coordinates) != 2 or not all(map(math.isfinite, coordinates)) or not (77.2 <= coordinates[0] <= 78 and 12.5 <= coordinates[1] <= 13.5):
        raise ValueError(f'Invalid Bengaluru-area point in placemark {index + 1}')
    properties['id'] = 'fire_station_' + (properties.get('KGISFIRE_STAID') or str(index + 1))
    properties['coordinate_source'] = 'Original KML point'
    features.append({'type': 'Feature', 'id': properties['id'], 'properties': properties, 'geometry': {'type': 'Point', 'coordinates': coordinates}})
if not features or len({feature['id'] for feature in features}) != len(features):
    raise ValueError('Empty dataset or duplicate station IDs')
output = Path(__file__).resolve().parent.parent / 'data'
(output / 'bengaluru-fire-stations.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': features}), encoding='utf-8')
(output / 'bengaluru-fire-stations.metadata.json').write_text(json.dumps({'sourceFile': args.input.name, 'sourceSha256': hashlib.sha256(args.input.read_bytes()).hexdigest(), 'featureCount': len(features), 'coordinateSource': 'Original KML point coordinates; no geocoding or snapping.', 'fields': 'All original SimpleData fields preserved as strings.', 'limitations': ['Survey date and source license are not specified in the supplied file.', 'Dataset includes stations outside the initial central Bengaluru viewport.']}, indent=2), encoding='utf-8')
print(f'Imported {len(features)} fire stations with original coordinates.')
