"""Deterministic Oracle APEX analysis.

Parses an APEX application export (and, where available, an Oracle data
dictionary extract) into a knowledge graph: pages, regions, items, processes,
the SQL and PL/SQL they run, and the database objects that SQL touches.

Every node and edge traces back to a byte in an export file or a row in a
dictionary extract; nothing here is inferred by a language model. The graph
vocabulary is defined in `constants.py` and enforced by
`graph/validate_rules.py`.
"""
from analyzer_core.model import Graph, GraphNode, GraphRel

from .constants import SCHEMA_VERSION

__all__ = ['Graph', 'GraphNode', 'GraphRel', 'SCHEMA_VERSION']
__version__ = '1.0.0'
