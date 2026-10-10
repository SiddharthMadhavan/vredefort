"""Compare matched-hour model results without changing their underlying data."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ComparisonMetric:
    label: str
    before: float
    after: float
    unit: str = ''

    @property
    def change(self):
        return self.after - self.before


def comparison_metrics(baseline, scenario, report):
    if baseline.hour != scenario.hour or baseline.links.keys() != scenario.links.keys():
        raise ValueError('Comparison requires the same hour and road graph')
    common = [identifier for identifier, state in scenario.links.items()
              if not state.closed and not baseline.links[identifier].closed]
    before_mean = sum(baseline.links[key].congestion for key in common) / len(common) if common else None
    after_mean = sum(scenario.links[key].congestion for key in common) / len(common) if common else None
    # A fixed population prevents closing a congested road from falsely looking
    # like a congestion improvement simply because it disappeared from a mean.
    metrics = []
    if common:
        metrics.append(ComparisonMetric('Mean congestion · common open roads', before_mean * 100, after_mean * 100, '%'))
    metrics.extend([
        ComparisonMetric('Heavy roads · common open roads (70%+)',
                         sum(baseline.links[key].congestion >= .7 for key in common),
                         sum(scenario.links[key].congestion >= .7 for key in common)),
        ComparisonMetric('Blocked roads', sum(state.closed for state in baseline.links.values()), len(report.closed_roads)),
        ComparisonMetric('Roads receiving extra traffic', 0, len(report.loaded_roads)),
        ComparisonMetric('Rerouted demand', baseline.rerouted_demand, scenario.rerouted_demand, 'veh/h'),
        ComparisonMetric('Unmet demand', baseline.unmet_demand, scenario.unmet_demand, 'veh/h'),
        ComparisonMetric('Nearby facilities · potential access delay', 0, len(report.facilities)),
    ])
    return metrics


def format_metric(value, unit='', signed=False):
    number = f'{value:+,.2f}' if signed and unit == '%' else f'{value:,.2f}' if unit == '%' else (
        f'{value:+,.0f}' if signed else f'{value:,.0f}')
    return number + ((' pp' if signed else '%') if unit == '%' else f' {unit}' if unit else '')
