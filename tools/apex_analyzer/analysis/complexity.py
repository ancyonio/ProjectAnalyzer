"""Page and application complexity, and the graph metrics behind it.

The score is deterministic and its weights live in one place
(`constants.COMPLEXITY_WEIGHTS`), so a team that disagrees with the weighting
can change it once and regenerate rather than argue with a black box.
"""
from __future__ import annotations

from typing import Dict, Optional

from analyzer_core.model import Graph
from analyzer_core.utils import tier_for

from ..constants import COMPLEXITY_TIERS, COMPLEXITY_WEIGHTS
from .traverse import descend, label_counts, write_targets


def annotate_complexity(graph: Graph, application_id: Optional[int] = None) -> None:
    """Write `complexityScore`, `tier` and the counts behind them onto pages,
    then aggregate onto the application."""
    pages = graph.by_label('ApexPage')
    for page in pages:
        reach = descend(graph, page.node_id, max_depth=8)
        counts = label_counts(graph, reach)
        writes = write_targets(graph, list(reach) + [page.node_id])
        unresolved = sum(1 for node_id in reach
                         if 'Unresolved' in str(graph.node(node_id).properties.get(
                             'extraLabels', '')))
        js_lines = sum(int(graph.node(n).properties.get('lineCount', 0) or 0)
                       for n in reach if graph.node(n).label == 'JsSnippet')

        metrics = {
            'regionCount': counts.get('ApexRegion', 0),
            'itemCount': counts.get('ApexItem', 0),
            'processCount': counts.get('ApexProcess', 0),
            'dynamicActionCount': counts.get('ApexDynamicAction', 0),
            'validationCount': counts.get('ApexValidation', 0),
            'branchCount': counts.get('ApexBranch', 0),
            'sqlStatementCount': counts.get('SqlStatement', 0),
            'plsqlBlockCount': counts.get('PlsqlBlock', 0),
            'tableCount': counts.get('DbTable', 0) + counts.get('DbView', 0),
            'packageCount': counts.get('DbPackage', 0),
            'writeCount': len(writes),
            'unresolvedCount': unresolved,
            'jsWeight': round(js_lines / 50.0, 2),
        }
        score = sum(COMPLEXITY_WEIGHTS.get(key, 0.0) * value
                    for key, value in metrics.items())
        page.properties.update({k: v for k, v in metrics.items() if k != 'jsWeight'})
        page.properties['complexityScore'] = round(score, 2)
        page.properties['tier'] = tier_for(score, COMPLEXITY_TIERS)
        page.properties['fanOut'] = counts.get('DbTable', 0) + counts.get('DbView', 0) + \
            counts.get('DbPackage', 0)
        page.properties['dependencyDepth'] = max(reach.values()) if reach else 0

    _annotate_db_fan_in(graph)
    _annotate_application(graph, application_id, pages)


def _annotate_db_fan_in(graph: Graph) -> None:
    """How many pages reach each database object — the change-risk number."""
    from .traverse import ascend
    for label in ('DbTable', 'DbView', 'DbPackage', 'DbProgramUnit'):
        for node in graph.by_label(label):
            reaching = ascend(graph, node.node_id, max_depth=8)
            pages = sum(1 for node_id in reaching
                        if graph.node(node_id).label == 'ApexPage')
            node.properties['fanIn'] = pages


def _annotate_application(graph: Graph, application_id: Optional[int], pages) -> None:
    applications = graph.by_label('ApexApplication')
    if not applications:
        return
    total = len(pages)
    scores = [float(p.properties.get('complexityScore', 0) or 0) for p in pages]
    secured = sum(1 for p in pages
                  if any(r.rel_type == 'SECURED_BY' for r in graph.outgoing(p.node_id)))
    sql_nodes = graph.by_label('SqlStatement')
    sql_edges = sum(1 for r in graph.rels if r.rel_type == 'EXECUTES_SQL')

    for application in applications:
        application.properties.update({
            'pageCount': total,
            'complexityScore': round(sum(scores), 2),
            'meanPageComplexity': round(sum(scores) / total, 2) if total else 0.0,
            'maxPageComplexity': round(max(scores), 2) if scores else 0.0,
            'authCoverage': round(secured / total, 4) if total else 0.0,
            'sqlReuseFactor': round(sql_edges / len(sql_nodes), 2) if sql_nodes else 0.0,
            'tableCount': len(graph.by_label('DbTable')),
            'packageCount': len(graph.by_label('DbPackage')),
        })

    mean = (sum(scores) / total) if total else 0.0
    for page in pages:
        fan_out = float(page.properties.get('fanOut', 0) or 0)
        page.properties['couplingIndex'] = round(fan_out / mean, 3) if mean else 0.0
