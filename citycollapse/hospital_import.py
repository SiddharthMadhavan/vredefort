"""Repeatable, offline import of the supplied Bengaluru healthcare KMLs.

Run python -m citycollapse.hospital_import --uphc FILE --clinics FILE
    --referral FILE --output data
Coordinates come only from KML Point geometry, never address guesses.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET


NS = {'k': 'http://www.opengis.net/kml/2.2'}
SOURCES = {
    'uphc': ('UPHC', 'Urban primary health centre', 'bengaluru-uphc.kml', 'FID'),
    'clinics': ('NammaClinicName', 'Namma Clinic', 'bengaluru-namma-clinics.kml', 'KGISNammaClinicID'),
    'referral': ('UCHC_HospitalName', 'Referral hospital', 'bengaluru-referral-hospitals.kml', 'KGISUCHC_RefferalHospitalID'),
}


def parse_hospitals(path, category):
    path = Path(path)
    name_field, facility_type, stored_name, id_field = SOURCES[category]
    root = ET.fromstring(path.read_bytes())
    features = []
    for row, placemark in enumerate(root.findall('.//k:Placemark', NS), 1):
        fields = {element.attrib['name']: ''.join(element.itertext()).strip()
                  for element in placemark.findall('.//k:SimpleData', NS)}
        fields.update({element.attrib['name']: element.findtext('k:value', default='', namespaces=NS).strip()
                       for element in placemark.findall('.//k:Data', NS)})
        name = fields.get(name_field) or placemark.findtext('k:name', default='', namespaces=NS).strip()
        points = placemark.findall('.//k:Point', NS)
        if not name or len(points) != 1:
            raise ValueError(f'{path.name} row {row}: facility needs a name and one Point geometry')
        coordinate_text = points[0].findtext('k:coordinates', default='', namespaces=NS).strip()
        if len(coordinate_text.split()) != 1:
            raise ValueError(f'{path.name} row {row}: invalid Point coordinates')
        try:
            coordinate = [float(v) for v in coordinate_text.split(',')[:2]]
        except ValueError as error:
            raise ValueError(f'{path.name} row {row}: invalid coordinates') from error
        if len(coordinate) != 2 or not all(math.isfinite(v) for v in coordinate) or \
                not (-180 <= coordinate[0] <= 180 and -90 <= coordinate[1] <= 90):
            raise ValueError(f'{path.name} row {row}: out-of-range coordinates')
        # Stable IDs use source category + supplied ID; content hash handles files
        # with missing IDs. Keep the source name and fields without inventing care
        # capacity, emergency wards, dispatch bases or opening hours.
        identifier = fields.get(id_field) or hashlib.sha256(
            json.dumps([name, coordinate], ensure_ascii=False).encode()).hexdigest()[:16]
        properties = {'id': f'healthcare_{category}_{identifier}', 'Name': name, 'Type': facility_type,
            'facility_category': category, 'match_status': 'provided_kml_coordinates',
            'coordinate_source': 'Supplied KML Point geometry', 'source_file': path.name,
            'bundled_source_file': f'sources/{stored_name}', 'source_row': row,
            'source_fields': fields, 'Ward': fields.get('ward') or fields.get('WardCode', ''),
            'Zone': fields.get('Zone') or fields.get('ZoneCode', ''),
            'Contact': fields.get('Contact_No', '')}
        features.append({'type': 'Feature', 'properties': properties,
                         'geometry': {'type': 'Point', 'coordinates': coordinate}})
    if not features:
        raise ValueError(f'{path.name}: no healthcare placemarks found')
    return features


def import_hospitals(sources, output):
    features, provenance, bundled, duplicates, seen, identifiers = [], [], [], [], {}, set()
    for category in SOURCES:
        path = Path(sources[category])
        rows = parse_hospitals(path, category)
        stored_name = SOURCES[category][2]
        payload = path.read_bytes()
        provenance.append({'file': path.name, 'bundled_file': f'sources/{stored_name}',
                           'sha256': hashlib.sha256(payload).hexdigest(), 'recordCount': len(rows),
                           'facility_type': SOURCES[category][1]})
        bundled.append((stored_name, payload))
        for feature in rows:
            properties = feature['properties']
            lon, lat = feature['geometry']['coordinates']
            key = category, re.sub(r'\W+', '', properties['Name'].casefold()), round(lon, 7), round(lat, 7)
            if key in seen:
                duplicates.append({'id': properties['id'], 'kept_id': seen[key],
                                   'source_file': properties['source_file'], 'source_row': properties['source_row']})
                continue
            if properties['id'] in identifiers:
                raise ValueError(f'Conflicting facility ID: {properties["id"]}')
            seen[key] = properties['id']
            identifiers.add(properties['id'])
            features.append(feature)
    if not features:
        raise ValueError('No healthcare points found')
    collection = {'type': 'FeatureCollection', 'features': features}
    metadata = {'recordCount': sum(p['recordCount'] for p in provenance), 'mappedCount': len(features),
        'unresolvedCount': 0, 'duplicateCount': len(duplicates), 'duplicates': duplicates,
        'categoryCounts': dict(Counter(f['properties']['facility_category'] for f in features)),
        'sources': provenance, 'coordinateSource': 'Coordinates supplied directly in KML Point geometry (longitude, latitude).',
        'geocodingUsed': False, 'inferredCount': 0, 'providedCoordinateCount': len(features),
        'notes': 'Replaces the earlier CSV/geocoded healthcare dataset. Primary health centres, clinics and referral '
                 'hospitals remain distinct categories. Care capability, ambulance dispatch, availability and capacity are unknown.'}
    # Validate everything before replacing the application's datasets.
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'sources').mkdir(exist_ok=True)
    for stored_name, payload in bundled:
        (output / 'sources' / stored_name).write_bytes(payload)
    for name, value in [('bengaluru-hospitals.geojson', collection), ('bengaluru-hospitals.metadata.json', metadata)]:
        target = output / name
        temporary = target.with_suffix(target.suffix + '.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(target)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for category in SOURCES:
        parser.add_argument(f'--{category}', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('data'))
    args = parser.parse_args()
    result = import_hospitals({category: getattr(args, category) for category in SOURCES}, args.output)
    print(json.dumps({key: result[key] for key in ('recordCount', 'mappedCount', 'duplicateCount', 'categoryCounts')}, indent=2))


if __name__ == '__main__':
    main()
