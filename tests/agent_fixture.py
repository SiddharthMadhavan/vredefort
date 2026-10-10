"""Explicit test-only HTTP fixtures; never used by the application."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
import time
from urllib.parse import urlsplit, parse_qs


@contextmanager
def fixture_server(chat_delay=.06, chat_status=200, flow_status=200, chat_fail_role=None):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_json(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            requests.append(('GET', query))
            if flow_status != 200:
                self.send_json(flow_status, {'error': 'Test-only provider error'})
                return
            lat, lon = map(float, query['point'][0].split(','))
            self.send_json(200, {'flowSegmentData': {
                'currentSpeed': 24, 'freeFlowSpeed': 48,
                'currentTravelTime': 120, 'freeFlowTravelTime': 60,
                'confidence': .8, 'roadClosure': False, 'openlr': 'fixture-fragment',
                'coordinates': {'coordinate': [
                    {'longitude': lon - .0005, 'latitude': lat},
                    {'longitude': lon + .0005, 'latitude': lat}]}}})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(('POST', body))
            if chat_status != 200 or (chat_fail_role and chat_fail_role in body['messages'][0]['content']):
                self.send_json(chat_status if chat_status != 200 else 500, {'error': 'Test-only missing model'})
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/x-ndjson')
            self.end_headers()
            chunks = ['Test fixture analyst: ', 'current speed is 24 km/h. ',
                      'Provider observation age is unknown.']
            if 'Historical Traffic Analyst' in body['messages'][0]['content']:
                chunks = ['## Synthetic historical overview\n\n',
                          '**Synthetic baseline — demonstration only.**\n\n',
                          '- Test fixture historical analyst: the synthetic baseline is 20 km/h.\n'
                          '- This does not describe measured historical traffic.']
            elif 'Network Bottleneck Analyst' in body['messages'][0]['content']:
                chunks = ['## Confirmed network facts\n\n',
                          '**Test fixture network analyst.**\n\n',
                          'Connectivity is inferred; the historical baseline is synthetic.']
            elif 'Road Improvement Planner' in body['messages'][0]['content']:
                chunks = ['## Candidate improvements\n\n',
                          '**Test fixture improvement planner.**\n\n',
                          'Measure turning movements before evaluating a signal-timing pilot.']
            elif 'Critical Reviewer' in body['messages'][0]['content']:
                chunks = ['## Review findings\n\n',
                          '**Test fixture critical reviewer.**\n\n',
                          '## Final priorities\n\nConfirm field conditions; the historical baseline is synthetic.']
            try:
                for text in chunks:
                    time.sleep(chat_delay)
                    self.wfile.write((json.dumps({'message': {'content': text}, 'done': False}) + '\n').encode())
                    self.wfile.flush()
                self.wfile.write(b'{"message":{"content":""},"done":true}\n')
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', requests
    finally:
        server.shutdown()
        server.server_close()


def fixture_network():
    from vredefort.data import Road, SpatialIndex
    from vredefort.explore_map import RoadNetwork
    from vredefort.geometry import project
    coordinates = [(77.6, 12.97), (77.601, 12.97), (77.602, 12.97)]
    nodes = [{'id': f'n{i}', 'number': i + 1, 'degree': 2 if i == 1 else 1,
              'kind': 'endpoint', 'coordinate': point, 'point': project(*point)}
             for i, point in enumerate(coordinates)]
    roads = []
    for i in range(2):
        path = (nodes[i]['point'], nodes[i + 1]['point'])
        xs, ys = zip(*path)
        roads.append(Road(f'e{i}', {'source': f'n{i}', 'target': f'n{i + 1}',
                                   'length_m': 108, 'names': []}, (path,),
                          (min(xs), min(ys), max(xs), max(ys))))
    return RoadNetwork(roads, SpatialIndex(r.bounds for r in roads), nodes,
                       SpatialIndex((*n['point'], *n['point']) for n in nodes),
                       {r.id: r for r in roads}, {n['id']: n for n in nodes},
                       {'n0': ['e0'], 'n1': ['e0', 'e1'], 'n2': ['e1']})
