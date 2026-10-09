"""Run two independent analysts over one selection and one live traffic fetch."""
from concurrent.futures import CancelledError

from .historical_traffic import HistoricalTrafficAnalyst
from .live_traffic import LiveTrafficAnalyst, check_cancel


class TrafficAnalysts:
    def __init__(self, config):
        self.live = LiveTrafficAnalyst(config)
        self.historical = HistoricalTrafficAnalyst(config)

    def analyze(self, network, road_id, cancel, emit):
        def for_agent(agent):
            return lambda kind, value: emit('agent_event', {'agent': agent, 'kind': kind, 'value': value})

        live_emit, history_emit = for_agent('live'), for_agent('historical')
        history_emit('status', 'Queued / synthetic historical analyst runs after the live analyst')
        live_evidence = None
        try:
            live_evidence = self.live.collect_evidence(network, road_id, cancel, live_emit)
            self.live.analyze_evidence(live_evidence, cancel, live_emit)
        except CancelledError:
            raise
        except Exception as error:
            check_cancel(cancel)
            live_emit('error', str(error) if isinstance(error, ValueError) else 'Live analysis failed. Check TomTom and Ollama, then retry.')
        check_cancel(cancel)
        try:
            self.historical.analyze(network, road_id, cancel, history_emit, live_evidence)
        except CancelledError:
            raise
        except Exception as error:
            check_cancel(cancel)
            history_emit('error', str(error) if isinstance(error, ValueError) else 'Historical analysis failed. Check the synthetic dataset and Ollama, then retry.')
