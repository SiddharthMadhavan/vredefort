from concurrent.futures import CancelledError
import json
from threading import Event, Thread
import unittest
from unittest.mock import patch

from citycollapse.live_traffic import AnalysisCancel, LiveTrafficAnalyst, normalize_flow, road_context, sample_road
from agent_fixture import fixture_network, fixture_server


class AnalystTests(unittest.TestCase):
    def setUp(self):
        self.network = fixture_network()
        self.config = {'tomtom_key': 'fixture-key', 'model': 'llama3.1:8b',
                       'ollama_url': 'http://127.0.0.1:11434'}

    def test_context_includes_each_connected_edge_once(self):
        context = road_context(self.network, 'e0')
        self.assertEqual([s['edge_id'] for s in context['samples']], ['e0', 'e1'])
        self.assertEqual(len(context['junctions']), 2)
        self.assertEqual(context['samples'][1]['junctions'], ['End node 2'])

    def test_missing_key_does_not_fabricate_or_fetch_traffic(self):
        config = {**self.config, 'tomtom_key': ''}
        def unexpected_request(*args, **kwargs):
            self.fail('Should not request traffic without a key')
        evidence = LiveTrafficAnalyst(config, unexpected_request).collect_evidence(
            self.network, 'e0', AnalysisCancel(), lambda *args: None)
        self.assertEqual(evidence['available_samples'], 0)
        for sample in evidence['observations']:
            self.assertEqual(sample['status'], 'unavailable')
            self.assertIsNone(sample['retrieved_at_utc'])
            self.assertNotIn('currentSpeed', sample)

    def test_http_collection_and_ollama_stream_are_grounded(self):
        with fixture_server() as (url, requests), patch('citycollapse.live_traffic.FLOW_URL', url + '/flow'):
            events = []
            LiveTrafficAnalyst({**self.config, 'ollama_url': url}).analyze(
                self.network, 'e0', AnalysisCancel(), lambda *event: events.append(event))
        evidence = next(value for kind, value in events if kind == 'evidence')
        self.assertEqual(evidence['available_samples'], 2)
        self.assertEqual(evidence['observations'][0]['delay_seconds'], 60)
        self.assertEqual(evidence['observations'][0]['speed_ratio'], .5)
        self.assertIsNone(evidence['observations'][0]['observation_time_utc'])
        self.assertIs(evidence['observations'][0]['roadClosure'], False)
        self.assertTrue(evidence['observations'][0]['retrieved_at_utc'])
        body = next(body for method, body in requests if method == 'POST')
        self.assertEqual(body['model'], 'llama3.1:8b')
        self.assertTrue(body['stream'])
        self.assertNotIn('fixture-key', json.dumps(body))
        self.assertEqual(json.loads(body['messages'][1]['content']), json.loads(json.dumps(evidence)))
        self.assertEqual(len([kind for kind, _ in events if kind == 'token']), 3)
        self.assertEqual(events[-1][0], 'done')

    def test_quota_error_stops_more_provider_calls_and_remains_unknown(self):
        with fixture_server(flow_status=429) as (url, requests), patch('citycollapse.live_traffic.FLOW_URL', url + '/flow'):
            evidence = LiveTrafficAnalyst(self.config).collect_evidence(
                self.network, 'e0', AnalysisCancel(), lambda *args: None)
        self.assertEqual(len(requests), 1)
        self.assertEqual(evidence['available_samples'], 0)
        self.assertTrue(all('limit' in sample['reason'] for sample in evidence['observations']))

    def test_model_not_found_has_actionable_error(self):
        with fixture_server(chat_status=404) as (url, requests):
            with self.assertRaisesRegex(ValueError, 'ollama pull llama3.1:8b'):
                LiveTrafficAnalyst({**self.config, 'tomtom_key': '', 'ollama_url': url}).analyze(
                    self.network, 'e0', AnalysisCancel(), lambda *args: None)

    def test_cancellation_interrupts_blocked_stream(self):
        first_token = Event()
        failures = []
        cancel = AnalysisCancel()
        with fixture_server(chat_delay=1) as (url, requests):
            analyst = LiveTrafficAnalyst({**self.config, 'tomtom_key': '', 'ollama_url': url})
            def run():
                try:
                    analyst.analyze(self.network, 'e0', cancel,
                                    lambda kind, value: first_token.set() if kind == 'token' else None)
                except CancelledError:
                    pass
                except Exception as error:
                    failures.append(error)
            worker = Thread(target=run, daemon=True)
            worker.start()
            self.assertTrue(first_token.wait(3))
            cancel.set()
            worker.join(.5)
            self.assertFalse(worker.is_alive(), 'Cancellation left the network read blocked')
            self.assertFalse(failures)

    def test_unrelated_fragment_and_invalid_values_are_rejected(self):
        coordinate, direction = sample_road(self.network.roads_by_id['e0'])
        base = {'currentSpeed': 24, 'freeFlowSpeed': 48, 'currentTravelTime': 120,
                'freeFlowTravelTime': 60, 'confidence': .8, 'roadClosure': False,
                'coordinates': {'coordinate': [{'longitude': 78, 'latitude': 13},
                                               {'longitude': 78.001, 'latitude': 13}]}}
        with self.assertRaisesRegex(ValueError, 'align'):
            normalize_flow({'flowSegmentData': base}, coordinate, direction)
        with self.assertRaisesRegex(ValueError, 'currentSpeed'):
            normalize_flow({'flowSegmentData': {**base, 'currentSpeed': True}}, coordinate, direction)
        with self.assertRaises(ValueError):
            normalize_flow({'flowSegmentData': {**base, 'coordinates': None}}, coordinate, direction)


if __name__ == '__main__':
    unittest.main()
