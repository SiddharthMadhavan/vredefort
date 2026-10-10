from concurrent.futures import CancelledError
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from citycollapse.agent_catalog import AGENTS
from citycollapse.historical_traffic import HistoricalDataset
from citycollapse.live_traffic import AnalysisCancel
from citycollapse.planning_agents import prior_reports
from citycollapse.traffic_agents import TrafficAnalysts
from agent_fixture import fixture_network, fixture_server
from history_fixture import write_history


class PlanningPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.history = write_history(self.folder / 'history.csv')
        self.network = fixture_network()
        self.config = {'model': 'llama3.1:8b', 'tomtom_key': 'fixture-key',
                       'history_csv': str(self.history), 'network_model': 'network-fixture',
                       'planner_model': 'planner-fixture', 'review_model': 'review-fixture'}

    def pipeline(self, url):
        pipeline = TrafficAnalysts({**self.config, 'ollama_url': url})
        pipeline.historical.dataset = HistoricalDataset(self.history, self.folder / 'cache')
        return pipeline

    def test_five_distinct_roles_receive_facts_and_prior_opinions(self):
        events = []
        with fixture_server() as (url, requests), patch('citycollapse.live_traffic.FLOW_URL', url + '/flow'):
            reports = self.pipeline(url).analyze(self.network, 'e0', AnalysisCancel(), lambda *event: events.append(event))
        prompts = [body for kind, body in requests if kind == 'POST']
        self.assertEqual(len(prompts), 5)
        self.assertEqual(len([body for kind, body in requests if kind == 'GET']), 2)
        self.assertEqual([body['model'] for body in prompts[2:]], ['network-fixture', 'planner-fixture', 'review-fixture'])
        self.assertTrue(all(body['options']['num_ctx'] == 16384 for body in prompts[2:]))
        self.assertEqual(list(reports), [spec.key for spec in AGENTS])
        self.assertTrue(all(report['status'] == 'complete' for report in reports.values()))
        expected_prior = [['live', 'historical'], ['live', 'historical', 'network'],
                          ['live', 'historical', 'network', 'planner']]
        evidences = {value['agent']: value['value'] for kind, value in events if
                     kind == 'agent_event' and value['kind'] == 'evidence'}
        for body, spec, prior in zip(prompts[2:], AGENTS[2:], expected_prior):
            payload = json.loads(body['messages'][1]['content'])
            self.assertEqual(payload, json.loads(json.dumps(evidences[spec.key])))
            self.assertEqual([report['agent'] for report in payload['prior_agent_reports']], prior)
            self.assertTrue(payload['historical_baseline_is_synthetic'])
            self.assertTrue(payload['computed_network_facts']['alternative_connection_without_selected_edge']['selected_edge_is_bridge_in_dataset'])
            self.assertEqual(payload['traffic_evidence']['live']['unique_available_provider_fragments'], 1)
            self.assertEqual(len(payload['traffic_evidence']['live']['provider_fragment_groups'][0]['edge_ids']), 2)
            self.assertNotIn('fixture-key', json.dumps(payload))
        self.assertIn('Test fixture improvement planner', evidences['review']['prior_agent_reports'][3]['analysis'])
        self.assertEqual(events[-1], ('pipeline_status', 'Finished / 5 complete, 0 failed, 0 incomplete'))

    def test_planner_failure_is_labelled_and_review_still_runs(self):
        events = []
        with fixture_server(chat_fail_role='Road Improvement Planner') as (url, requests), \
                patch('citycollapse.live_traffic.FLOW_URL', url + '/flow'):
            reports = self.pipeline(url).analyze(self.network, 'e0', AnalysisCancel(), lambda *event: events.append(event))
        self.assertEqual(reports['planner']['status'], 'failed')
        self.assertEqual(reports['review']['status'], 'complete')
        review = json.loads([body for kind, body in requests if kind == 'POST'][-1]['messages'][1]['content'])
        failed = next(report for report in review['prior_agent_reports'] if report['agent'] == 'planner')
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['analysis'], '')
        self.assertIn('HTTP 500', failed['error'])
        self.assertIn('4 complete, 1 failed', events[-1][1])

    def test_missing_history_does_not_become_real_history_downstream(self):
        self.history.unlink()
        with fixture_server() as (url, requests), patch('citycollapse.live_traffic.FLOW_URL', url + '/flow'):
            reports = self.pipeline(url).analyze(self.network, 'e0', AnalysisCancel(), lambda *args: None)
        self.assertEqual(reports['historical']['status'], 'failed')
        review = json.loads([body for kind, body in requests if kind == 'POST'][-1]['messages'][1]['content'])
        history = review['traffic_evidence']['historical']
        self.assertEqual(history['status'], 'unavailable')
        self.assertEqual(history['observations'], [])
        self.assertTrue(history['synthetic'])

    def test_cancel_network_stream_stops_planner_and_reviewer_requests(self):
        cancel = AnalysisCancel()
        def emit(kind, value):
            if kind == 'agent_event' and value['agent'] == 'network' and value['kind'] == 'token':
                cancel.set()
        with fixture_server() as (url, requests), patch('citycollapse.live_traffic.FLOW_URL', url + '/flow'):
            with self.assertRaises(CancelledError):
                self.pipeline(url).analyze(self.network, 'e0', cancel, emit)
        self.assertEqual(len([body for kind, body in requests if kind == 'POST']), 3)

    def test_unfinished_upstream_output_is_not_marked_complete(self):
        with fixture_server() as (url, requests), patch('citycollapse.live_traffic.FLOW_URL', url + '/flow'):
            pipeline = self.pipeline(url)
            def partial_planner(evidence, cancel, emit):
                emit('evidence', evidence)
                emit('token', 'A partial candidate.\n\n[Reply reached its length limit.]')
                emit('done', 'Length limit reached')
            pipeline.planning['planner'].analyze = partial_planner
            reports = pipeline.analyze(self.network, 'e0', AnalysisCancel(), lambda *args: None)
        self.assertEqual(reports['planner']['status'], 'incomplete')
        review = json.loads([body for kind, body in requests if kind == 'POST'][-1]['messages'][1]['content'])
        self.assertEqual(review['prior_agent_reports'][-1]['status'], 'incomplete')

    def test_long_prior_output_is_explicitly_excerpted(self):
        report = prior_reports({'planner': {'status': 'complete', 'analysis': 'x' * 3000}})[0]
        self.assertTrue(report['excerpt_truncated'])
        self.assertEqual(len(report['analysis']), 2400)


if __name__ == '__main__':
    unittest.main()
