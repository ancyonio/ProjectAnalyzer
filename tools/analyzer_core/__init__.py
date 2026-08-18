"""Dialect-agnostic analysis core.

Everything in this package is independent of the technology being analysed:
the graph data model, id construction, the Neo4j exporter, the validation
engine, the blast-radius engine and the Cypher cookbook renderer.

`tibco_analyzer` and `apex_analyzer` both build on it; nothing here may
import from either.
"""
from .model import Graph, GraphNode, GraphRel

__all__ = ['Graph', 'GraphNode', 'GraphRel']
__version__ = '1.0.0'
