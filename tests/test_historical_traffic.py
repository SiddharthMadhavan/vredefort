from concurrent.futures import CancelledError
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from citycollapse.historical_traffic import HistoricalDataset, HistoricalTrafficAnalyst
from citycollapse.live_traffic import AnalysisCancel
from citycollapse.traffic_agents import TrafficAnalysts
from agent_fixture import fixture_network, fixture_server
from history_fixture import write_history


class HistoricalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.path = write_history(self.folder / 'synthetic.csv')
        self.dataset = HistoricalDataset(self.path, self.folder / 'cache')
        self.network = fixture_network()
        self.config = {'history_csv': str(self.path), 'model': 'llama3.1:8b',
                       'ollama_url': 'http://127.0.0.1:11434', 'tomtom_key': ''}
        self.live = {'requested_at_utc': '2026-10-10T03:30:00+00:00', 'observations': [
            {'edge_id': 'e0', 'status': 'available', 'currentSpeed': 24,
             'provider_fragment_id': 'fixture-fragment', 'match': 'nearby fragment'}]}

    def evidence(self):
        return HistoricalTrafficAnalyst(self.config, self.dataset).collect_evidence(
            self.network, 'e0', AnalysisCancel(), lambda *args: None, self.live)

    def test_exact_edge_stats_time_zone_and_synthetic_comparison(self):
        evidence = self.evidence()
        self.assertTrue(evidence['synthetic'])
        self.assertEqual(evidence['reference_time_ist'], '2026-10-10T09:00:00+05:30')
        self.assertEqual(evidence['available_samples'], 2)
        observation = evidence['observations'][0]
        baseline = observation['synthetic_history']
        self.assertEqual(baseline['overall']['samples'], 21)
        self.assertEqual(baseline['overall']['distinct_dates'], 7)
        self.assertEqual(baseline['overall']['median_speed_kmh'], 20)
        self.assertEqual(baseline['slowest_observed_hours_ist'][0]['hour_ist'], 18)
        self.assertEqual(baseline['same_weekday_hour']['samples'], 1)
        self.assertFalse(baseline['same_weekday_hour_recurring_support'])
        self.assertEqual(observation['illustrative_speed_comparison']['difference_kmh'], 4)
        self.assertIn('not a real historical anomaly', observation['illustrative_speed_comparison']['limitation'])
        self.assertNotIn('hourly_profile_ist', evidence['observations'][1]['synthetic_history'])

    def test_future_rows_are_excluded_and_empty_history_is_not_invented(self):
        earlier = {**self.live, 'requested_at_utc': '2026-09-30T00:00:00+00:00'}
        evidence = HistoricalTrafficAnalyst(self.config, self.dataset).collect_evidence(
            self.network, 'e0', AnalysisCancel(), lambda *args: None, earlier)
        self.assertEqual(evidence['available_samples'], 0)
        self.assertEqual(evidence['observations'][0]['synthetic_history']['samples'], 0)
        self.assertNotIn('illustrative_speed_comparison', evidence['observations'][0])

    def test_missing_edge_is_not_nearest_neighbour_substituted(self):
        reference = datetime(2026, 10, 10, tzinfo=timezone.utc)
        _, rows = self.dataset.load(['different-edge'], reference, AnalysisCancel(), lambda *args: None)
        self.assertEqual(rows, {'different-edge': []})

    def test_duplicates_invalid_rows_and_persistent_index(self):
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write('e0,2026-10-01 09:00:00,999,100,2,50,40,0\n')
            stream.write('e0,2026-10-01 10:00:00,nan,100,2,50,40,0\n')
            stream.write('e0,bad-date,24,100,2,50,40,0\n')
        evidence = self.evidence()
        self.assertEqual(evidence['dataset']['invalid_rows_skipped'], 2)
        self.assertEqual(evidence['dataset']['duplicate_edge_timestamps_skipped'], 1)
        self.assertEqual(evidence['observations'][0]['synthetic_history']['overall']['median_speed_kmh'], 20)
        def unexpected_status(*args):
            self.fail('Existing index should not reimport CSV')
        self.dataset.index(AnalysisCancel(), unexpected_status)

    def test_gzip_input_and_bad_schema(self):
        compressed = self.folder / 'synthetic.csv.gz'
        with gzip.open(compressed, 'wb') as stream:
            stream.write(self.path.read_bytes())
        dataset = HistoricalDataset(compressed, self.folder / 'gzip-cache')
        metadata, rows = dataset.load(['e0'], datetime(2026, 10, 10, tzinfo=timezone.utc), AnalysisCancel(), lambda *args: None)
        self.assertEqual(metadata['indexed_rows'], 42)
        self.assertEqual(len(rows['e0']), 21)
        self.path.write_text('edge_id,Date\ne0,bad\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'metric columns'):
            self.dataset.index(AnalysisCancel(), lambda *args: None)
        self.assertFalse(list(self.dataset.cache_dir.glob('*.building')))

    def test_cancellation_does_not_leave_partial_index(self):
        cancel = AnalysisCancel()
        cancel.set()
        with self.assertRaises(CancelledError):
            self.dataset.index(cancel, lambda *args: None)
        self.assertFalse(list(self.dataset.cache_dir.glob('*.building')))

    def test_cancellation_during_import_removes_unfinished_database(self):
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write('e0,2026-10-01 09:00:00,20,100,2,50,40,0\n' * 6000)
        cancel = AnalysisCancel()
        def stop_on_progress(*args):
            cancel.set()
        with self.assertRaises(CancelledError):
            self.dataset.index(cancel, stop_on_progress)
        self.assertFalse(list(self.dataset.cache_dir.glob('*.building')))

    def test_both_agents_share_fetch_and_ground_separate_ollama_calls(self):
        with fixture_server() as (url, requests), patch('citycollapse.live_traffic.FLOW_URL', url + '/flow'):
            agents = TrafficAnalysts({**self.config, 'tomtom_key': 'fixture-key', 'ollama_url': url})
            agents.historical.dataset = self.dataset
            events = []
            agents.analyze(self.network, 'e0', AnalysisCancel(), lambda *event: events.append(event))
        self.assertEqual(len([request for kind, request in requests if kind == 'GET']), 2)
        prompts = [body for kind, body in requests if kind == 'POST']
        self.assertEqual(len(prompts), 5)
        self.assertIn('Live Traffic Analyst', prompts[0]['messages'][0]['content'])
        self.assertIn('Historical Traffic Analyst', prompts[1]['messages'][0]['content'])
        self.assertIn('synthetic', prompts[1]['messages'][0]['content'].lower())
        payload = json.loads(prompts[1]['messages'][1]['content'])
        evidence = next(value['value'] for kind, value in events if
                        kind == 'agent_event' and value['agent'] == 'historical' and value['kind'] == 'evidence')
        self.assertEqual(payload, json.loads(json.dumps(evidence)))
        self.assertNotIn('fixture-key', json.dumps(prompts))
        self.assertEqual({value['agent'] for kind, value in events if kind == 'agent_event' and value['kind'] == 'done'},
                         {'live', 'historical', 'network', 'planner', 'review'})

    def test_live_agent_survives_missing_history_dataset(self):
        with fixture_server() as (url, requests):
            agents = TrafficAnalysts({**self.config, 'history_csv': str(self.folder / 'missing.csv'), 'ollama_url': url})
            events = []
            agents.analyze(self.network, 'e0', AnalysisCancel(), lambda *event: events.append(event))
        self.assertTrue(any(value['agent'] == 'live' and value['kind'] == 'done' for kind, value in events if kind == 'agent_event'))
        errors = [value for kind, value in events if kind == 'agent_event' and value['kind'] == 'error']
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['agent'], 'historical')


if __name__ == '__main__':
    unittest.main()
