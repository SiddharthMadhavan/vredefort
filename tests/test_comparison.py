from dataclasses import replace
from types import SimpleNamespace
import unittest

from test_traffic import model_fixture
from vredefort.comparison import comparison_metrics, format_metric
from vredefort.presentation import display_evidence, display_text


def report_for(result, facilities=()):
    return SimpleNamespace(
        closed_roads={key for key, state in result.links.items() if state.closed},
        loaded_roads={key for key, state in result.links.items() if not state.closed and state.flow > state.baseline},
        facilities=facilities)


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.model = model_fixture([('ab', 'a', 'b', 100), ('ac', 'a', 'c', 100), ('cb', 'c', 'b', 100)])
        self.before = self.model.solve(0)

    def metrics(self, scenario, facilities=()):
        return {metric.label: metric for metric in comparison_metrics(self.before, scenario, report_for(scenario, facilities))}

    def test_no_closures_have_zero_changes(self):
        self.assertTrue(all(metric.change == 0 for metric in self.metrics(self.before).values()))

    def test_road_closure_compares_flow_and_access_flags(self):
        after = self.model.solve(0, {'ab'})
        metrics = self.metrics(after, ('hospital', 'fire station'))
        self.assertEqual(metrics['Blocked roads'].after, 1)
        self.assertEqual(metrics['Roads receiving extra traffic'].after, 2)
        self.assertEqual(metrics['Rerouted demand'].change, 50)
        self.assertEqual(metrics['Unmet demand'].after, 0)
        self.assertEqual(metrics['Nearby facilities · potential access delay'].change, 2)
        self.assertFalse(self.before.links['ab'].closed)

    def test_junction_closures_and_unmet_demand(self):
        after = self.model.solve(0, blocked_nodes={'a'})
        metrics = self.metrics(after)
        self.assertEqual(metrics['Blocked roads'].after, 2)
        self.assertAlmostEqual(after.affected_demand, metrics['Rerouted demand'].after + metrics['Unmet demand'].after)
        bridge = model_fixture([('ab', 'a', 'b', 100)])
        result = bridge.solve(0, {'ab'})
        values = comparison_metrics(bridge.solve(0), result, report_for(result))
        self.assertEqual(next(value.after for value in values if value.label == 'Unmet demand'), 50)

    def test_same_population_and_no_false_zero_when_all_closed(self):
        links = dict(self.before.links)
        links['ab'] = replace(links['ab'], congestion=1.)
        before = replace(self.before, links=links)
        after = self.model.solve(0, {'ab'})
        mean = comparison_metrics(before, after, report_for(after))[0]
        self.assertAlmostEqual(mean.before, 20.)
        all_closed = self.model.solve(0, set(self.before.links))
        self.assertFalse(any(metric.unit == '%' for metric in self.metrics(all_closed).values()))

    def test_mismatched_hour_or_graph_rejected(self):
        for invalid in (replace(self.before, hour=1), replace(self.before, links={})):
            with self.assertRaises(ValueError):
                comparison_metrics(self.before, invalid, report_for(invalid))

    def test_format_changes_use_percentage_points(self):
        self.assertEqual(format_metric(12.5, '%', True), '+12.50 pp')
        self.assertEqual(format_metric(2500, 'veh/h'), '2,500 veh/h')

    def test_display_copy_preserves_raw_provenance_and_numbers(self):
        evidence = {'synthetic': True, 'source': 'Synthetic baseline',
                    'observations': [{'edge_id': 'ab', 'synthetic_history': {'flow': 23.5}}],
                    'path': 'data/synthetic.csv'}
        display = display_evidence(evidence)
        self.assertTrue(evidence['synthetic'])
        self.assertEqual(evidence['path'], 'data/synthetic.csv')
        self.assertTrue(display['model_generated'])
        self.assertEqual(display['observations'][0]['historical_baseline']['flow'], 23.5)
        self.assertEqual(display['observations'][0]['edge_id'], 'ab')
        self.assertNotIn('synthetic', str(display).lower())
        self.assertNotIn('path', display)
        self.assertEqual(display_text('SYNTHETIC / synthetic'), 'model-generated / model-generated')
