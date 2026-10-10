from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from citycollapse.data import DATA, read_points
from citycollapse.hospital_import import SOURCES, import_hospitals, parse_hospitals


def write_kml(path, category, rows):
    name_field, _, _, id_field = SOURCES[category]
    placemarks = ''.join(f'<Placemark><ExtendedData><SchemaData>'
        f'<SimpleData name="{name_field}">{name}</SimpleData><SimpleData name="{id_field}">{identifier}</SimpleData>'
        '<SimpleData name="ward">Test ward</SimpleData></SchemaData></ExtendedData>'
        f'<Point><coordinates>{coordinate}</coordinates></Point></Placemark>' for identifier, name, coordinate in rows)
    path.write_text(f'<kml xmlns="http://www.opengis.net/kml/2.2"><Document>{placemarks}</Document></kml>')
    return path


class HospitalImportTests(unittest.TestCase):
    def test_import_keeps_exact_coordinates_categories_source_fields_and_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sources = {kind: write_kml(root / (kind + '.kml'), kind, [('0', kind, '77.60123456789,12.98123456789,0')]) for kind in SOURCES}
            result = import_hospitals(sources, root / 'out')
            data = json.loads((root / 'out/bengaluru-hospitals.geojson').read_text())
            self.assertEqual(result['mappedCount'], 3)
            self.assertFalse(result['geocodingUsed'])
            self.assertEqual(result['inferredCount'], 0)
            for feature in data['features']:
                self.assertEqual(feature['geometry']['coordinates'], [77.60123456789, 12.98123456789])
                properties = feature['properties']
                self.assertEqual(properties['Ward'], 'Test ward')
                self.assertEqual(properties['match_status'], 'provided_kml_coordinates')
                self.assertNotIn('Beds', properties)
            for source in result['sources']:
                payload = (root / 'out' / source['bundled_file']).read_bytes()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), source['sha256'])

    def test_dedup_only_same_name_type_and_location(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sources = {kind: write_kml(root / (kind + '.kml'), kind, [('1', 'Same', '77.6,13')]) for kind in SOURCES}
            write_kml(sources['uphc'], 'uphc', [('1', 'Same', '77.6,13'), ('2', ' SAME ', '77.6,13')])
            result = import_hospitals(sources, root / 'out')
            self.assertEqual(result['recordCount'], 4)
            self.assertEqual(result['mappedCount'], 3)
            self.assertEqual(result['duplicateCount'], 1)

    def test_invalid_coordinates_or_conflicting_ids_preserve_existing_dataset(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sources = {kind: write_kml(root / (kind + '.kml'), kind, [('1', kind, '77.6,13')]) for kind in SOURCES}
            output = root / 'out'
            import_hospitals(sources, output)
            original = (output / 'bengaluru-hospitals.geojson').read_bytes()
            for rows in ([('1', 'Invalid', 'nan,13')], [('1', 'Invalid', '77.6,99')],
                         [('1', 'First', '77.6,13'), ('1', 'Different', '77.7,13')]):
                write_kml(sources['uphc'], 'uphc', rows)
                with self.assertRaises(ValueError):
                    import_hospitals(sources, output)
                self.assertEqual((output / 'bengaluru-hospitals.geojson').read_bytes(), original)

    def test_actual_dataset_matches_all_three_bundled_sources(self):
        points, _ = read_points('bengaluru-hospitals.geojson')
        metadata = json.loads((DATA / 'bengaluru-hospitals.metadata.json').read_text())
        self.assertEqual(len(points), 255)
        self.assertEqual(Counter(p['facility_category'] for p in points), {'uphc': 139, 'clinics': 109, 'referral': 7})
        self.assertEqual(len({p['id'] for p in points}), 255)
        self.assertEqual(metadata['mappedCount'], len(points))
        by_id = {p['id']: p for p in points}
        for category, source in zip(SOURCES, metadata['sources']):
            path = DATA / source['bundled_file']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source['sha256'])
            for feature in parse_hospitals(path, category):
                point = by_id[feature['properties']['id']]
                self.assertEqual(point['coordinate'], feature['geometry']['coordinates'])
                self.assertEqual(point['Name'], feature['properties']['Name'])
                self.assertEqual(point['Type'], feature['properties']['Type'])
