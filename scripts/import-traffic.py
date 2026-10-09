"""Validate the supplied synthetic hourly CSV and create a compact local cache."""
import argparse
from array import array
import csv
from datetime import datetime, timedelta
import gzip
import hashlib
import json
import math
from pathlib import Path
from statistics import median
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from citycollapse.data import DATA, load_json
from citycollapse.traffic import FIELDS


def import_csv(source, destination=DATA):
    source, destination = Path(source), Path(destination)
    edges = [edge['id'] for edge in load_json('bengaluru-kml-road-graph.json')['edges']]
    edge_index = {identifier: i for i, identifier in enumerate(edges)}
    snapshots, seen = {}, set()
    capacity_samples = [[] for _ in edges]
    rows_count = 0
    with source.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not {'Date', 'edge_id', *FIELDS} <= set(reader.fieldnames or []):
            raise ValueError('CSV is missing required traffic columns')
        for number, row in enumerate(reader, 2):
            identifier, hour = row['edge_id'], row['Date']
            if identifier not in edge_index:
                raise ValueError(f'Unknown edge on row {number}: {identifier}')
            timestamp = datetime.strptime(hour, '%Y-%m-%d %H:%M:%S')
            if timestamp.minute or timestamp.second:
                raise ValueError(f'Non-hourly timestamp on row {number}')
            index = edge_index[identifier]
            key = (hour, index)
            if key in seen:
                raise ValueError(f'Duplicate edge/hour on row {number}')
            seen.add(key)
            values = [float(row[field]) for field in FIELDS]
            q, speed, tti, congestion, utilization = values
            if (not all(math.isfinite(v) for v in values) or q < 0 or speed <= 0
                    or tti < 1 or not 0 <= congestion <= 100 or not 0 < utilization <= 100):
                raise ValueError(f'Invalid traffic measurements on row {number}')
            snapshot = snapshots.setdefault(hour, array('f', [math.nan]) * (len(edges) * 5))
            snapshot[index * 5:index * 5 + 5] = array('f', values)
            # Utilization is capped at 100% in the synthetic CSV. Use uncapped hours.
            if utilization < 95:
                capacity_samples[index].append(q / (utilization / 100))
            rows_count += 1
    hours = sorted(snapshots)
    if not hours:
        raise ValueError('No traffic rows')
    for a, b in zip(hours, hours[1:]):
        if datetime.fromisoformat(b) - datetime.fromisoformat(a) != timedelta(hours=1):
            raise ValueError('Missing hourly timestamp')
    if any(any(not math.isfinite(v) for v in snapshot) for snapshot in snapshots.values()):
        raise ValueError('Every hourly snapshot must contain every graph edge')
    if any(not sample or median(sample) <= 0 for sample in capacity_samples):
        raise ValueError('Insufficient positive uncapped capacity observations for an edge')
    with source.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    metadata = {
        'format': 'float32-le-hour-edge-5-v1', 'fields': list(FIELDS),
        'source_filename': source.name, 'source_sha256': digest,
        'source_rows': rows_count, 'synthetic': True, 'hours': hours, 'edge_ids': edges,
        'capacities_veh_h': [median(sample) for sample in capacity_samples],
        'capacity_method': 'Median volume/(utilization/100) for each edge, only hours below 95% utilization.',
        'units_assumed': {'Traffic Volume': 'vehicles/hour, total both directions', 'Average Speed': 'km/h',
                          'Congestion Level': 'percent', 'Road Capacity Utilization': 'percent'},
        'time_zone_assumed': 'Asia/Kolkata (CSV has no timezone)',
        'limitations': ['Synthetic inputs, not observed Bengaluru traffic.',
                       'No origin-destination trips or turning counts; closures use conditional local-trip assumptions.',
                       'Undirected graph has unverified junction topology and no signals/turn restrictions.',
                       'Quasi-static hourly assignment; no physical queues, spillback or vehicle interactions.']
    }
    destination.mkdir(parents=True, exist_ok=True)
    with gzip.open(destination / 'bengaluru-traffic.bin.gz', 'wb', compresslevel=6) as stream:
        for hour in hours:
            snapshot = snapshots[hour]
            if sys.byteorder != 'little':
                snapshot.byteswap()
            stream.write(snapshot.tobytes())
    (destination / 'bengaluru-traffic.metadata.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    print(f'Imported {rows_count:,} rows / {len(hours)} hours / {len(edges):,} matched roads')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', type=Path)
    parser.add_argument('--output', type=Path, default=DATA)
    args = parser.parse_args()
    import_csv(args.csv, args.output)
