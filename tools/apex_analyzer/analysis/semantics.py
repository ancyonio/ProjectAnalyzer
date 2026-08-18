"""Business layer seeding.

The specification reserves `:BusinessDomain`, `:BusinessFunction` and
`:BusinessTransaction` for agent reasoning. The analyzer seeds them from the
one piece of business intent APEX actually records — the page group — and
from whether a page writes to the database, so an agent starts from something
grounded instead of a blank sheet.

Everything created here is stamped `origin:'derived'` with a confidence and an
evidence list. An agent that refines a name or a boundary must keep the
evidence and set `origin:'llm'`.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from analyzer_core.ids import business_domain_id, business_function_id
from analyzer_core.model import Graph, GraphNode, GraphRel

from .traverse import descend, write_targets

UNASSIGNED = 'Unassigned'


def seed_business_layer(graph: Graph, application_id: Optional[int] = None,
                        dataset_id: str = '') -> int:
    """Create the derived business seed. Returns the number of nodes added."""
    pages = graph.by_label('ApexPage')
    if not pages:
        return 0

    added = 0
    domains: Dict[str, str] = {}

    for page in pages:
        group = str(page.properties.get('pageGroup') or '').strip() or UNASSIGNED
        domain_node = domains.get(group)
        if domain_node is None:
            domain_node = business_domain_id(group)
            graph.nodes[domain_node] = GraphNode(domain_node, 'BusinessDomain', group, {
                'name': group,
                'origin': 'derived',
                'confidence': 0.5,
                'description': f'Derived from the APEX page group "{group}"'
                               if group != UNASSIGNED else
                               'Pages with no page group assigned',
                'datasetId': dataset_id,
            })
            domains[group] = domain_node
            added += 1

        reach = descend(graph, page.node_id, max_depth=8)
        writes = write_targets(graph, list(reach) + [page.node_id])
        if not writes:
            continue        # a read-only page is not a business transaction

        function_node = business_function_id(group, page.name)
        if function_node in graph.nodes:
            continue
        tables = sorted({graph.node(t).name for t in writes if graph.node(t)})
        graph.nodes[function_node] = GraphNode(function_node, 'BusinessFunction',
                                               page.name, {
            'name': page.name,
            'domain': group,
            'origin': 'derived',
            'confidence': 0.4,
            'criticality': 'HIGH' if len(tables) > 2 else 'MEDIUM',
            'description': f'Page {page.properties.get("pageId")} writes to '
                           f'{", ".join(tables[:5])}',
            'evidence': page.node_id,
            'datasetId': dataset_id,
        })
        added += 1
        graph.rels.append(GraphRel(function_node, page.node_id, 'IMPLEMENTED_BY',
                                   {'origin': 'derived', 'confidence': 0.4}))
        graph.rels.append(GraphRel(function_node, domain_node, 'PART_OF_DOMAIN',
                                   {'origin': 'derived', 'confidence': 0.5}))

    graph.reindex()
    return added
