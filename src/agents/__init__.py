"""Agentes do produto (classes Python simples)."""

from src.agents.llm_client import LLMClient, LLMResult, get_client
from src.agents.specialists import (
    AgentOutput,
    MarketAgent,
    RegulatoryAgent,
    RiskAgent,
    TraderAgent,
)

__all__ = [
    "AgentOutput", "LLMClient", "LLMResult", "MarketAgent", "RegulatoryAgent",
    "RiskAgent", "TraderAgent", "get_client",
]
