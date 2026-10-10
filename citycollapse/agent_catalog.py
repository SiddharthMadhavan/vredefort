"""One ordered agent catalog for the pipeline, model configuration, and GUI."""
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    key: str
    title: str
    choice: str
    model_key: str
    badge: str


AGENTS = (
    AgentSpec('live', 'LIVE TRAFFIC ANALYST', '01 Live', 'model', ''),
    AgentSpec('historical', 'HISTORICAL TRAFFIC ANALYST', '02 History', 'history_model',
              'HISTORICAL BASELINE'),
    AgentSpec('network', 'NETWORK BOTTLENECK ANALYST', '03 Network bottlenecks', 'network_model',
              'INFERRED GRAPH'),
    AgentSpec('planner', 'ROAD IMPROVEMENT PLANNER', '04 Road improvements', 'planner_model',
              'CONDITIONAL PROPOSALS'),
    AgentSpec('review', 'CRITICAL REVIEW + FINAL RECOMMENDATIONS', '05 Review and final recommendations', 'review_model',
              'REVIEWED PROPOSALS'),
)
AGENT_BY_KEY = {agent.key: agent for agent in AGENTS}
AGENT_BY_CHOICE = {agent.choice: agent for agent in AGENTS}


def agent_models(config):
    return {agent.key: config.get(agent.model_key, config['model']) for agent in AGENTS}
