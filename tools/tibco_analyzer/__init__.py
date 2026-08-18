"""Deterministic TIBCO BusinessWorks analysis toolkit.

Layer 1 (this package) extracts verifiable facts from TIBCO artefacts.
Layer 2 (the GitHub Copilot skill and prompts) reasons over those facts.
The boundary is deliberate: counts, dependencies and blast radii are never
produced by a language model.
"""
from .analyzer import TibcoAnalyzer
from .model import Graph, GraphNode, GraphRel

__version__ = '1.0.0'
__all__ = ['TibcoAnalyzer', 'Graph', 'GraphNode', 'GraphRel', '__version__']
