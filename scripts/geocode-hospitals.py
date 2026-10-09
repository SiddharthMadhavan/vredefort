"""One-time, sequential Photon lookup with cached results and conservative facility matching."""
import argparse
import csv
from difflib import SequenceMatcher
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / 'data'
CACHE = DATA / 'hospital-geocoding-cache.json'
STOP = {'bbmp', 'hospital', 'hospitals', 'health', 'centre', 'center', 'maternity', 'home', 'referral', 'urban', 'family', 'welfare', 'bangalore', 'bengaluru', 'road', 'government', 'primary', 'the'}

def tokens(text):
    return set(re.findall(r'[a-z0-9]+', text.lower())) - STOP

def expanded(name):
    return re.sub(r'\bH\.?\s*C\.?', 'Health Centre', re.sub(r'\bUFWC\b', 'Urban Family Welfare Centre', name), flags=re.I)

def match(record, candidates):
    wanted = tokens(expanded(record['Name']))
    ranked = []
    for candidate in candidates:
        p = candidate.get('properties', {})
        lon, lat = candidate.get('geometry', {}).get('coordinates', [0, 0])[:2]
        if not (77.35 <= lon <= 77.85 and 12.75 <= lat <= 13.25):
            continue
        if p.get('osm_value') not in {'hospital', 'clinic', 'doctors', 'health_post'}:
            continue  # Never use street/locality centroids as hospital coordinates.
        expected_postcode = re.search(r'(?:Bangalore|Bengaluru)\s*[^\d]*([0-9]{2})\s*$', record.get('Address', ''), re.I)
        if expected_postcode and p.get('postcode') and p['postcode'] != '5600' + expected_postcode.group(1):
            continue
        candidate_name = p.get('name', '').lower()
        if any(word in record.get('Type', '') for word in ['Health Centre', 'Family Welfare']) and not re.search(r'bbmp|government|govt|uphc|phc|primary health|urban health|health cent(?:re|er)|welfare', candidate_name):
            continue
        if 'maternity' in record['Name'].lower() and 'maternity' not in candidate_name:
            continue
        if 'maternity' not in record['Name'].lower() and 'maternity' in candidate_name:
            continue
        found = tokens(p.get('name', ''))
        overlap = len(wanted & found) / max(1, len(wanted))
        normalized_wanted = ''.join(sorted(wanted))
        normalized_found = ''.join(sorted(found - {'uphc', 'phc'}))
        spelling_similarity = SequenceMatcher(None, normalized_wanted, normalized_found).ratio() if normalized_wanted and normalized_found else 0
        if spelling_similarity >= .88:
            overlap = max(overlap, spelling_similarity)
        if overlap >= .75:
            address_words = tokens(record.get('Address', ''))
            result_address = tokens(' '.join(str(p.get(key, '')) for key in ['street', 'district', 'locality', 'city']))
            address_agreement = len(address_words & result_address) / max(1, len(result_address))
            ranked.append((overlap + .3 * address_agreement, candidate))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked:
        return None
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < .2:
        return None  # Competing facilities need review.
    return ranked[0][1]
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('files', nargs='+', type=Path)
    args = parser.parse_args()
    DATA.mkdir(exist_ok=True)
    records = []
    for path in args.files:
        with path.open(encoding='utf-8-sig', newline='') as stream:
            for line, row in enumerate(csv.reader(stream)):
                if line == 0:
                    headers = row
                    continue
                # Some original rows contain surplus empty columns. Preserve the raw row.
                values = dict(zip(headers, row))
                values['Contact'] = row[-1] if row else ''
                if not values.get('Name', '').strip():
                    continue
                records.append({**values, 'id': 'hospital_' + hashlib.sha256((path.name + ':' + str(line)).encode()).hexdigest()[:12], 'source_file': path.name, 'source_row': line + 1, 'raw_values': row})
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    endpoint = os.environ.get('HOSPITAL_GEOCODER_URL', 'https://photon.komoot.io/api/')
    last_request = 0
    features, unresolved = [], []
    for index, record in enumerate(records):
        query = expanded(record['Name']) + ', Bengaluru'
        if query not in cache:
            time.sleep(max(0, 2 - (time.monotonic() - last_request)))
            url = endpoint + '?' + urllib.parse.urlencode({'q': query, 'limit': 5, 'lang': 'en', 'lat': 12.9716, 'lon': 77.5946})
            request = urllib.request.Request(url, headers={'User-Agent': 'CityCollapse-hospital-import/1.0'})
            last_request = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    cache[query] = json.load(response).get('features', [])
            except Exception as error:
                print(f'Lookup stopped: {type(error).__name__}: {error}', flush=True)
                raise  # Do not cache failures or continue hitting a throttled service.
            CACHE.write_text(json.dumps(cache), encoding='utf-8')
        osm_cache = DATA / 'hospital-osm-facilities.json'
        local_candidates = json.loads(osm_cache.read_text()) if osm_cache.exists() else []
        candidates = {}
        for c in cache[query] + local_candidates:
            identity = str(c.get('properties', {}).get('osm_type')) + str(c.get('properties', {}).get('osm_id'))
            previous = candidates.get(identity, {})
            candidates[identity] = {**c, 'properties': {**previous.get('properties', {}), **c.get('properties', {})}}
        candidate = match(record, list(candidates.values()))
        if candidate:
            p = candidate['properties']
            features.append({'type': 'Feature', 'id': record['id'], 'properties': {**record, 'match_status': 'inferred_facility_match', 'matched_name': p.get('name'), 'osm_type': p.get('osm_type'), 'osm_id': p.get('osm_id'), 'matched_address': ', '.join(str(p.get(key)) for key in ['housenumber', 'street', 'district', 'city', 'postcode'] if p.get(key)), 'geocoder': 'OpenStreetMap facility matching'}, 'geometry': candidate['geometry']})
        else:
            unresolved.append({**record, 'reason': 'No unambiguous named healthcare facility match', 'query': query, 'candidates': cache[query]})
        print(f'{index + 1}/{len(records)}: {record["Name"]}: {"matched" if candidate else "needs review"}', flush=True)
    (DATA / 'bengaluru-hospitals.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': features}), encoding='utf-8')
    (DATA / 'bengaluru-hospitals.unresolved.json').write_text(json.dumps(unresolved, indent=2), encoding='utf-8')
    (DATA / 'bengaluru-hospitals.metadata.json').write_text(json.dumps({'recordCount': len(records), 'mappedCount': len(features), 'unresolvedCount': len(unresolved), 'sources': [{'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in args.files], 'geocoder': endpoint, 'coordinateSource': 'OpenStreetMap named healthcare POIs via Photon; points can represent building or site centroids.', 'matching': 'Healthcare POI within Bengaluru bounds, at least 75% distinctive name token agreement, competing equal matches excluded. Inferred matches require verification; not authoritative hospital locations.', 'unresolved': 'Unmatched records retained separately. No address/locality centroid guesses.'}, indent=2), encoding='utf-8')
    metadata_path = DATA / 'bengaluru-hospitals.metadata.json'
    metadata = json.loads(metadata_path.read_text())
    metadata['coordinateSource'] = 'OpenStreetMap healthcare POIs via cached Photon queries and a bounded Overpass extract. Coordinates can represent building/site centroids.'
    metadata['matching'] = 'Healthcare POI in Bengaluru bounds; distinctive-name token agreement >=75% or normalized spelling similarity >=88%. Available postcode conflicts and facility-type conflicts rejected. Address token agreement ranks candidates; close competing scores excluded. All matches are inferred and need verification.'
    if osm_cache.exists():
        metadata['osmExtract'] = {'file': osm_cache.name, 'sha256': hashlib.sha256(osm_cache.read_bytes()).hexdigest(), 'endpoint': 'https://overpass-api.de/api/interpreter'}
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(f'Saved {len(features)} mapped; {len(unresolved)} unresolved.', flush=True)
    if (DATA / 'hospitals-provided-coordinates.json').exists():
        import runpy
        runpy.run_path(str(Path(__file__).with_name('merge-hospital-coordinates.py')), run_name='__main__')

if __name__ == '__main__':
    main()
