"""Run five agents, sharing source facts and explicitly labelled prior opinions."""
from concurrent.futures import CancelledError

from .historical_traffic import HistoricalTrafficAnalyst
from .live_traffic import LiveTrafficAnalyst, check_cancel
from .agent_catalog import AGENTS
from .network_analysis import network_facts
from .planning_agents import PlanningAnalyst, compact_inputs, planning_evidence
from .analysis_scope import scope_roads


class TrafficAnalysts:
    def __init__(self, config):
        self.live = LiveTrafficAnalyst(config)
        self.historical = HistoricalTrafficAnalyst(config)
        self.planning = {key: PlanningAnalyst(config, key) for key in ('network', 'planner', 'review')}

    def analyze(self, network, road_id, cancel, emit):
        scope_roads(network, road_id)
        reports, evidences = {}, {}
        graph = None

        def publish(agent, kind, value):
            emit('agent_event', {'agent': agent, 'kind': kind, 'value': value})

        for spec in AGENTS:
            publish(spec.key, 'status', 'Queued / waiting for earlier agents')

        def run_stage(spec, action):
            check_cancel(cancel)
            number = AGENTS.index(spec) + 1
            emit('pipeline_status', f'Running {number}/{len(AGENTS)} / {spec.title.title()}')
            chunks, completed, truncated = [], False, False

            def capture(kind, value):
                nonlocal completed, truncated
                check_cancel(cancel)
                if kind == 'evidence':
                    evidences[spec.key] = value
                elif kind == 'token':
                    chunks.append(value)
                    truncated |= '[Reply reached its length limit.]' in value
                elif kind == 'done':
                    completed = True
                publish(spec.key, kind, value)

            try:
                action(capture)
                check_cancel(cancel)
                reports[spec.key] = {'status': 'complete' if completed and not truncated else 'incomplete',
                                     'analysis': ''.join(chunks)}
            except CancelledError:
                raise
            except Exception as error:
                check_cancel(cancel)
                message = str(error) if isinstance(error, ValueError) else f'{spec.title.title()} failed. Check the source data and Ollama, then retry.'
                reports[spec.key] = {'status': 'failed', 'analysis': ''.join(chunks), 'error': message}
                publish(spec.key, 'error', message)

        def live_stage(capture):
            evidence = self.live.collect_evidence(network, road_id, cancel, capture)
            self.live.analyze_evidence(evidence, cancel, capture)

        def downstream_stage(agent, capture):
            nonlocal graph
            capture('status', 'Preparing graph facts and prior assessments...')
            if graph is None:
                graph = network_facts(network, road_id, cancel)
            inputs = compact_inputs(evidences.get('live'), evidences.get('historical'))
            evidence = planning_evidence(agent, graph, inputs, reports)
            self.planning[agent].analyze(evidence, cancel, capture)

        run_stage(AGENTS[0], live_stage)
        run_stage(AGENTS[1], lambda capture: self.historical.analyze(
            network, road_id, cancel, capture, evidences.get('live')))
        for spec in AGENTS[2:]:
            run_stage(spec, lambda capture, key=spec.key: downstream_stage(key, capture))
        complete = sum(report['status'] == 'complete' for report in reports.values())
        failed = sum(report['status'] == 'failed' for report in reports.values())
        incomplete = len(reports) - complete - failed
        emit('pipeline_status', f'Finished / {complete} complete, {failed} failed, {incomplete} incomplete')
        return reports
