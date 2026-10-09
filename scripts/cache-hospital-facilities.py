"""Download one bounded OSM healthcare extract to improve local facility matching."""
import json
import urllib.parse
import urllib.request
from pathlib import Path

output = Path(__file__).resolve().parent.parent / 'data/hospital-osm-facilities.json'
if output.exists():
    print('Using cached OSM facility extract.')
else:
    query = '[out:json][timeout:90];nwr[amenity~"^(hospital|clinic|doctors)$"](12.75,77.35,13.25,77.85);out center tags;'
    request = urllib.request.Request('https://overpass-api.de/api/interpreter', data=urllib.parse.urlencode({'data': query}).encode(), headers={'User-Agent': 'CityCollapse-hospital-import/1.0'})
    with urllib.request.urlopen(request, timeout=110) as response:
        payload = json.load(response)
    if payload.get('remark'):
        raise RuntimeError(payload['remark'])
    features = []
    for element in payload['elements']:
        tags = element.get('tags', {})
        point = element.get('center', element)
        if not tags.get('name') or 'lon' not in point:
            continue
        p = {'name': tags['name'], 'osm_type': {'node': 'N', 'way': 'W', 'relation': 'R'}[element['type']], 'osm_id': element['id'], 'osm_value': tags['amenity']}
        for key in ['street', 'postcode', 'city', 'housenumber', 'district']:
            if tags.get('addr:' + key):
                p[key] = tags['addr:' + key]
        features.append({'type': 'Feature', 'properties': p, 'geometry': {'type': 'Point', 'coordinates': [point['lon'], point['lat']]}})
    output.write_text(json.dumps(features), encoding='utf-8')
    print(f'Cached {len(features)} named healthcare facilities for local comparison.')
