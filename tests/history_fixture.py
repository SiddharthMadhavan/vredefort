"""Tiny synthetic history fixture, never a production fallback."""
import csv


def write_history(path, edge_ids=('e0', 'e1')):
    fields = ['edge_id', 'Date', 'Average Speed', 'Traffic Volume', 'Travel Time Index',
              'Congestion Level', 'Road Capacity Utilization', 'Incident Reports']
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for edge_id in edge_ids:
            for day in range(1, 8):
                for hour, speed in [(9, 20), (12, 40), (18, 10)]:
                    writer.writerow(dict(zip(fields, [edge_id, f'2026-10-{day:02} {hour:02}:00:00',
                                                       speed, 100, 2, 50, 40, 0])))
    return path
