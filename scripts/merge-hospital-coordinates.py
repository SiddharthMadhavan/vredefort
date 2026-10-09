"""Merge user-supplied coordinates without geocoding or silently relocating existing facilities."""
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlencode

DATA = Path(__file__).resolve().parent.parent / 'data'
SOURCE = 'hospitals-provided-coordinates.json'

def merge():
    provided = json.loads((DATA / SOURCE).read_text(encoding='utf-8'))
    collection = json.loads((DATA / 'bengaluru-hospitals.geojson').read_text(encoding='utf-8'))
    unresolved = json.loads((DATA / 'bengaluru-hospitals.unresolved.json').read_text(encoding='utf-8'))
    metadata = json.loads((DATA / 'bengaluru-hospitals.metadata.json').read_text(encoding='utf-8'))
    # Idempotent: replace only the records from this coordinate source.
    features = [feature for feature in collection['features'] if feature['properties'].get('source_file') != SOURCE]
    unresolved = [record for record in unresolved if record.get('source_file') != SOURCE]
    existing_names = {feature['properties']['Name'].strip().casefold() for feature in features}
    added = 0
    for row in provided:
        lon, lat = row['longitude'], row['latitude']
        if not all(math.isfinite(value) for value in [lon, lat]) or not (77.2 <= lon <= 78 and 12.5 <= lat <= 13.5):
            raise ValueError('Invalid supplied coordinates: ' + row['Name'])
        properties = {**row, 'id': 'provided_hospital_' + hashlib.sha256(row['Name'].encode()).hexdigest()[:12], 'source_file': SOURCE, 'coordinate_source': 'User-provided latitude/longitude', 'Type': 'Hospital', 'search_url': 'https://www.google.com/search?' + urlencode({'q': row['search_query']})}
        if row.get('review_reason'):
            unresolved.append({**properties, 'reason': row['review_reason']})
        elif row['Name'].strip().casefold() in existing_names:
            unresolved.append({**properties, 'reason': 'Name duplicates an existing mapped facility; review before replacing its coordinate.'})
        else:
            features.append({'type': 'Feature', 'id': properties['id'], 'properties': {**properties, 'match_status': 'provided_coordinates'}, 'geometry': {'type': 'Point', 'coordinates': [lon, lat]}})
            existing_names.add(row['Name'].strip().casefold())
            added += 1
    collection['features'] = features
    metadata.update({'recordCount': len(features) + len(unresolved), 'mappedCount': len(features), 'unresolvedCount': len(unresolved), 'providedCoordinateCount': added, 'inferredCount': sum(feature['properties']['match_status'] == 'inferred_facility_match' for feature in features), 'providedSource': {'file': SOURCE, 'recordCount': len(provided), 'sha256': hashlib.sha256((DATA / SOURCE).read_bytes()).hexdigest(), 'notes': 'Coordinates and addresses supplied in chat; not independently verified. Google search links are reference searches, not official hospital websites. One conflicting facility is withheld for review.'}})
    for name, value in [('bengaluru-hospitals.geojson', collection), ('bengaluru-hospitals.unresolved.json', unresolved), ('bengaluru-hospitals.metadata.json', metadata)]:
        (DATA / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{len(features)} mapped: {added} supplied coordinates, {metadata["inferredCount"]} inferred; {len(unresolved)} unresolved.')

if __name__ == '__main__':
    merge()
