"""Flammy - a vigilant fire-safety advisor agent for microgravity, lunar and normal gravity.

    from flammy_agent import FlammyAgent
    agent = FlammyAgent()
    advisory = agent.observe_simulation(gravity="lunar", material="fabric", o2=34)
"""
from .agent import FlammyAgent
from .engine import Advisory, advise
from . import knowledge

__all__ = ["FlammyAgent", "Advisory", "advise", "knowledge"]
__version__ = "1.0.0"
