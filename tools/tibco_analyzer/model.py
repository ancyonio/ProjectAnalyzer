"""Graph data model — moved to `analyzer_core.model`.

The model is dialect-agnostic and is now shared with the APEX analyzer. This
module stays as the import path every parser mixin already uses
(`from ..model import GraphNode`), so nothing inside `tibco_analyzer` had to
change when the model moved.

`SCHEMA_VERSION` is still exported here because `analyzer.py` writes it into
`graph.meta`, which is where `Graph.to_dict` now reads it from.
"""
from __future__ import annotations

from analyzer_core.model import DEFAULT_SCHEMA_VERSION, Graph, GraphNode, GraphRel

from .constants import SCHEMA_VERSION

__all__ = ['Graph', 'GraphNode', 'GraphRel', 'SCHEMA_VERSION', 'DEFAULT_SCHEMA_VERSION']
