"""Business layer seeding.

The estate vocabulary reserves `:BusinessDomain` and `:BusinessFunction` for
agent reasoning, and `apex_analyzer` already seeds them from the one piece of
business intent an APEX export records — the page group. This does the same job
for an Oracle tree, from the two things Oracle source actually states: which
package a unit belongs to, and whether that unit changes the database.

The rule is deliberately narrow. A unit that is callable from outside and
writes to a table is a business transaction; a private helper or a read-only
lookup is not. That keeps the seed to the handful of entry points a
modernisation conversation actually starts from, instead of restating the call
graph in business words.

Nothing here is inferred from what a name *sounds* like. Every node is stamped
`origin:'derived'` with a confidence and the node id it was derived from, so an
agent that renames a domain or redraws a boundary can see what it is overriding
— and a declared map (`--business-map`) supersedes the whole seed with
`origin:'declared'` and confidence 1.0, because a stated fact beats a derived
one.

Names are shared with `apex_analyzer` rather than spelled a second way: a
federated graph answers one `IMPLEMENTED_BY` query across both estates, which
is the entire point of a common vocabulary.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from analyzer_core.ids import business_domain_id, business_function_id
from analyzer_core.model import Graph, GraphNode

logger = logging.getLogger('oracle_analyzer')

_WRITE_RELS = ('INSERTS_INTO', 'UPDATES', 'DELETES_FROM', 'WRITES_TO')

# Suffixes that carry no business meaning: CUSTOMER_PKG and CUSTOMER_API are
# both the customer domain, and keeping the suffix would split it in two.
_NOISE_SUFFIX_RE = re.compile(
    r'_(PKG|PACKAGE|PKG_BODY|API|UTIL|UTILS|HELPER|SVC|SERVICE|MGR|MANAGER)$',
    re.IGNORECASE)

UNASSIGNED = 'Unassigned'


def domain_name(package: str, owner: str) -> str:
    """The domain a unit belongs to.

    A package is the only grouping an Oracle tree states, so it is the domain;
    a standalone unit has none and falls back to its schema.
    """
    if package:
        stem = _NOISE_SUFFIX_RE.sub('', package).strip('_')
        return (stem or package).replace('_', ' ').title()
    return (owner or UNASSIGNED).replace('_', ' ').title()


def _writes_of(graph: Graph, unit_id: str) -> List[str]:
    """Tables the unit changes, through the statements it runs."""
    targets: Set[str] = set()
    for rel in graph.outgoing(unit_id):
        if rel.rel_type != 'EXECUTES_SQL' or rel.end_id not in graph.nodes:
            continue
        for write in graph.outgoing(rel.end_id):
            if write.rel_type in _WRITE_RELS and write.end_id in graph.nodes:
                node = graph.nodes[write.end_id]
                if node.label in ('DbTable', 'DbView', 'DbMaterializedView'):
                    targets.add(node.name)
    return sorted(targets)


def _is_callable_from_outside(node: GraphNode) -> bool:
    """Published by a spec, or standalone. A private body unit is not a
    business function however much it writes -- something else calls it, and
    that something else is the transaction."""
    return bool(node.properties.get('isStandalone')
                or node.properties.get('isPublished'))


def load_business_map(path: Optional[Path]) -> Dict[str, Any]:
    """Read a declared domain map, or return an empty one.

    Shape (every key optional)::

        {
          "domains": {"Customer": "Customer Management"},
          "functions": {"CUSTOMER_PKG.CREATE_CUSTOMER": {
              "name": "Customer Onboarding", "domain": "Customer Management",
              "criticality": "HIGH"}}
        }

    A malformed file is a configuration error the run should surface, not
    absorb: silently falling back to the derived seed would leave the graph
    saying "derived" when the operator believes it says "declared".
    """
    if path is None:
        return {}
    if not path.exists():
        raise FileNotFoundError(f'Business map not found: {path}')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'Business map must be a JSON object: {path}')
    return data


def seed_business_layer(analyzer, business_map: Optional[Dict[str, Any]] = None) -> int:
    """Create the business seed over a finished graph. Returns nodes added."""
    business_map = business_map or {}
    declared_domains: Dict[str, str] = {
        str(k).upper(): str(v) for k, v in (business_map.get('domains') or {}).items()}
    declared_functions: Dict[str, Dict[str, Any]] = {
        str(k).upper(): v for k, v in (business_map.get('functions') or {}).items()
        if isinstance(v, dict)}

    graph = Graph(analyzer.nodes, analyzer.rels, {})
    units = [node for node in list(analyzer.nodes.values())
             if node.label == 'DbProgramUnit']

    added = 0

    def ensure_domain(name: str, declared: bool, evidence: str) -> str:
        nonlocal added
        node_id = business_domain_id(name)
        if node_id not in analyzer.nodes:
            analyzer._add_node(GraphNode(node_id, 'BusinessDomain', name, {
                'origin': 'declared' if declared else 'derived',
                'confidence': 1.0 if declared else 0.5,
                'description': 'Declared in the business map' if declared else
                               f'Derived from the package {evidence}',
                'evidence': evidence,
            }))
            added += 1
        return node_id

    for unit in sorted(units, key=lambda n: n.node_id):
        if unit.properties.get('declaredOnly'):
            continue                      # a spec entry with no implementation
        if not _is_callable_from_outside(unit):
            continue
        writes = _writes_of(graph, unit.node_id)
        if not writes:
            continue                      # a read-only unit is not a transaction

        package = str(unit.properties.get('packageName') or '')
        owner = str(unit.properties.get('owner') or '')
        key = f'{package}.{unit.name}'.strip('.').upper()
        override = declared_functions.get(key, {})

        # Provenance is per domain, not per run: a map that names one domain
        # must not stamp the rest as declared, or the confidence figure stops
        # meaning anything.
        derived_domain = domain_name(package, owner)
        stated = (override.get('domain')
                  or declared_domains.get(derived_domain.upper())
                  or declared_domains.get((package or owner).upper()))
        domain = str(stated) if stated else derived_domain
        domain_node = ensure_domain(domain, bool(stated), package or owner)

        function_name = str(override.get('name') or unit.name)
        function_node = business_function_id(domain, function_name)
        if function_node not in analyzer.nodes:
            declared = bool(override)
            analyzer._add_node(GraphNode(
                function_node, 'BusinessFunction', function_name, {
                    'domain': domain,
                    'origin': 'declared' if declared else 'derived',
                    'confidence': 1.0 if declared else 0.4,
                    'criticality': str(override.get('criticality')
                                       or ('HIGH' if len(writes) > 2 else 'MEDIUM')),
                    'description': f'{unit.name} writes to {", ".join(writes[:5])}',
                    'evidence': unit.node_id,
                    'writesTo': ', '.join(writes),
                }))
            added += 1
        analyzer._add_rel(function_node, unit.node_id, 'IMPLEMENTED_BY',
                          purpose='business-implementation')
        analyzer._add_rel(function_node, domain_node, 'PART_OF_DOMAIN',
                          purpose='business-grouping')

    functions = sum(1 for node in analyzer.nodes.values()
                    if node.label == 'BusinessFunction')
    if added:
        logger.info('  %d business node(s) seeded (%d function(s)) from %d unit(s)',
                    added, functions, len(units))
    else:
        logger.info('  no business seed: no published unit writes to the database')
    return added
