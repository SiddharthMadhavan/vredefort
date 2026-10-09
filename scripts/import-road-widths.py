"""Convert the supplied road-width KML to GeoJSON without third-party packages."""
import argparse
import collections
import datetime
import hashlib
import json
import pathlib
import xml.etree.ElementTree as ET

parser = argparse.ArgumentParser()
parser.add_argument('input', type=pathlib.Path)
args = parser.parse_args()
ns = {'k': 'http://www.opengis.net/kml/2.2'}
features = []
fields = ('RR_width_B', 'RR_WIDTH_P')
values = {field: [] for field in fields}
bounds = [float('inf'), float('inf'), float('-inf'), float('-inf')]
for _, placemark in ET.iterparse(args.input, events=('end',)):
    if placemark.tag != '{http://www.opengis.net/kml/2.2}Placemark':
        continue
    properties = {entry.attrib['name']: (entry.text or '').strip() for entry in placemark.findall('.//k:SimpleData', ns)}
    for field in ('OBJECTID', 'RR_CD', *fields):
        raw = properties.get(field)
        try:
            number = float(raw)
            properties[field] = number if number == number and abs(number) != float('inf') else None
        except (TypeError, ValueError):
            properties[field] = None
    lines = []
    for element in placemark.findall('.//k:LineString/k:coordinates', ns):
        points = []
        for token in (element.text or '').split():
            parts = token.split(',')
            lon, lat = float(parts[0]), float(parts[1])
            if not (77 < lon < 79 and 12 < lat < 14):
                raise ValueError('Unexpected coordinate outside Bengaluru region')
            if not points or points[-1] != [lon, lat]:
                points.append([lon, lat])
            bounds[0] = min(bounds[0], lon)
            bounds[1] = min(bounds[1], lat)
            bounds[2] = max(bounds[2], lon)
            bounds[3] = max(bounds[3], lat)
        if len(points) >= 2:
            lines.append(points)
    if not lines:
        raise ValueError('Placemark has no usable road geometry')
    index = len(features)
    properties['id'] = f'kml_road_{index + 1}'
    features.append({'type': 'Feature', 'id': properties['id'], 'properties': properties,
                     'geometry': {'type': 'MultiLineString', 'coordinates': lines}})
    for field in fields:
        if properties[field] is not None and properties[field] > 0:
            values[field].append(properties[field])
    placemark.clear()
if not features:
    raise ValueError('No roads in KML')
stats = {}
for field, numbers in values.items():
    numbers.sort()
    stats[field] = {'validCount': len(numbers), 'unknownCount': len(features) - len(numbers),
                    'min': numbers[0] if numbers else None, 'max': numbers[-1] if numbers else None,
                    'distribution': dict(sorted(collections.Counter(numbers).items()))}
output = pathlib.Path(__file__).resolve().parent.parent / 'data'
output.mkdir(exist_ok=True)
(output / 'bengaluru-road-widths.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': features}, separators=(',', ':'), ensure_ascii=False), encoding='utf8')
metadata = {'source': 'User-provided roadwidth KML', 'sourceFile': args.input.name,
            'sourceSha256': hashlib.sha256(args.input.read_bytes()).hexdigest(),
            'importedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'featureCount': len(features), 'bounds': bounds, 'widthFields': stats,
            'defaultWidthField': 'RR_WIDTH_P',
            'processing': 'Line geometries and original coordinate precision preserved. Consecutive identical points removed. Original fields retained.',
            'limitations': ['KML does not define width units or explain the two width fields.',
                            'Only positive finite field values are treated as known widths; zero/missing values are unknown.',
                            'KML feature IDs do not identify the OSM graph edges. No road-to-graph matching is inferred.',
                            'The KML contains no explicit source license or survey date.']}
(output / 'bengaluru-road-widths.metadata.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding='utf8')
print(json.dumps({'roads': len(features), 'bounds': bounds, 'widthFields': stats}, indent=2))
