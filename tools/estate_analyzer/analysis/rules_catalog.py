"""The cross-estate rule catalogue.

Every rule here answers a question that is *only* answerable once the estates
are joined. A rule that could be evaluated inside one analyzer belongs in that
analyzer, not in the wrapper: restating an APEX finding as a federation
discovery would inflate the ledger without adding information.

Rule ids are `XE-` plus an ordinal, stable and never reused. Findings become
`Issue` nodes with a `Recommendation`, in the same shape as the APEX and Oracle
catalogues, so one Cypher query answers all three.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set

from analyzer_core.ids import issue_id, recommendation_id
from analyzer_core.model import Graph, GraphNode

from ..constants import CONTENT_ID_PREFIXES, ESTATE_ID_SEP
from ..federate import Federation

WRITE_RELS = ('WRITES_TO', 'INSERTS_INTO', 'UPDATES', 'DELETES_FROM')
READ_RELS = ('READS_FROM',)
EXECUTION_RELS = ('EXECUTES_SQL', 'EXECUTES_PLSQL', 'EXECUTES')

# How far to walk up the APEX containment chain looking for the owning page.
_PAGE_SEARCH_DEPTH = 6


# ──────────────────────────────────────────────────────────────
def apply_rules(graph: Graph, federation: Federation,
                link_result: Dict[str, Any]) -> int:
    """Run every cross-estate rule and attach what it found."""
    findings: List[Dict[str, Any]] = []
    for rule in (_xe_001_multi_estate_writers,
                 _xe_002_unmodelled_table,
                 _xe_003_transaction_boundary,
                 _xe_004_duplicate_statement,
                 _xe_005_unmapped_datasource,
                 _xe_006_runtime_sql_at_the_boundary,
                 _xe_007_user_surface_over_integrated_table):
        findings.extend(rule(graph, link_result) or [])

    for finding in findings:
        _attach(graph, federation, finding)
    graph.reindex()
    return len(findings)


def _finding(rule_id: str, severity: str, target: str, description: str,
             recommendation: str, estates: Iterable[str] = ()) -> Dict[str, Any]:
    return {
        'ruleId': rule_id, 'severity': severity, 'category': 'CROSS_ESTATE',
        'target': target, 'description': description,
        'recommendation': recommendation, 'estates': sorted(set(estates)),
    }


def _attach(graph: Graph, federation: Federation, finding: Dict[str, Any]) -> None:
    target = finding['target']
    if target not in graph.nodes:
        return
    node_id = issue_id(finding['ruleId'], target)
    if node_id in graph.nodes:
        return
    target_node = graph.nodes[target]

    graph.nodes[node_id] = GraphNode(node_id, 'Issue', finding['ruleId'], {
        'ruleId': finding['ruleId'],
        'severity': finding['severity'],
        'category': finding['category'],
        'description': finding['description'],
        'targetLabel': target_node.label,
        'targetName': target_node.name,
        'filePath': str(target_node.properties.get('filePath', '') or ''),
        'estate': 'cross',
        'estates': ';'.join(finding['estates']),
    })
    federation.contributors.setdefault(node_id, ['cross'])
    federation.add_rel(target, node_id, 'HAS_ISSUE', {'purpose': 'rule-finding'})
    federation.add_rel(node_id, target, 'AFFECTS', {'purpose': 'finding-target'})

    rec_id = recommendation_id(node_id)
    graph.nodes[rec_id] = GraphNode(rec_id, 'Recommendation', finding['ruleId'], {
        'text': finding['recommendation'],
        'ruleId': finding['ruleId'],
        'severity': finding['severity'],
        'estate': 'cross',
    })
    federation.contributors.setdefault(rec_id, ['cross'])
    federation.add_rel(node_id, rec_id, 'HAS_RECOMMENDATION', {'purpose': 'remediation'})


# ──────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────
def _estate_of(node: Optional[GraphNode]) -> str:
    return str(node.properties.get('estate', '') or '') if node else ''


def _accessors(graph: Graph, table_id: str, rel_types: Iterable[str]
               ) -> List[GraphNode]:
    """Nodes that read or write a table, by any of the given edge types."""
    wanted = set(rel_types)
    out = []
    for rel in graph.incoming(table_id):
        if rel.rel_type in wanted and rel.start_id in graph.nodes:
            out.append(graph.nodes[rel.start_id])
    return out


def _executors(graph: Graph, node_id: str) -> List[GraphNode]:
    """Whatever executes a statement or block: the unit, process or page code."""
    out = []
    for rel in graph.incoming(node_id):
        if rel.rel_type in EXECUTION_RELS and rel.start_id in graph.nodes:
            out.append(graph.nodes[rel.start_id])
    return out


def _writer_estates(graph: Graph, table_id: str) -> Dict[str, List[GraphNode]]:
    by_estate: Dict[str, List[GraphNode]] = defaultdict(list)
    for node in _accessors(graph, table_id, WRITE_RELS):
        estate = _estate_of(node)
        if estate:
            by_estate[estate].append(node)
    return dict(by_estate)


def _describe(graph: Graph, node: GraphNode) -> str:
    """A writer named the way a reader of the report would name it."""
    if node.label in ('SqlStatement', 'PlsqlBlock'):
        owners = [owner.name for owner in _executors(graph, node.node_id)]
        if owners:
            return f"{owners[0]} ({node.label})"
    if node.label == 'Activity':
        process = _owning_process(graph, node)
        if process is not None:
            return f'{process.name}.{node.name}'
    return node.name


def _owning_process(graph: Graph, activity: GraphNode) -> Optional[GraphNode]:
    for rel in graph.incoming(activity.node_id):
        if rel.rel_type == 'EXECUTES' and rel.start_id in graph.nodes:
            candidate = graph.nodes[rel.start_id]
            if candidate.label == 'BWProcess':
                return candidate
    return None


def _apex_page_of(graph: Graph, node_id: str) -> Optional[GraphNode]:
    """Walk up the APEX containment chain to the page that owns a component."""
    seen: Set[str] = {node_id}
    frontier = [node_id]
    for _ in range(_PAGE_SEARCH_DEPTH):
        nxt: List[str] = []
        for current in frontier:
            for rel in graph.incoming(current):
                parent = graph.nodes.get(rel.start_id)
                if parent is None or parent.node_id in seen:
                    continue
                if parent.label == 'ApexPage':
                    return parent
                if _estate_of(parent) != 'apex':
                    continue
                seen.add(parent.node_id)
                nxt.append(parent.node_id)
        if not nxt:
            break
        frontier = nxt
    return None


def _tables_written_by(graph: Graph, estate: str) -> Dict[str, List[GraphNode]]:
    """Every database object the named estate writes, and what writes it."""
    out: Dict[str, List[GraphNode]] = defaultdict(list)
    for rel in graph.rels:
        if rel.rel_type not in WRITE_RELS:
            continue
        writer = graph.nodes.get(rel.start_id)
        if writer is None or _estate_of(writer) != estate:
            continue
        if rel.end_id in graph.nodes:
            out[rel.end_id].append(writer)
    return dict(out)


# ──────────────────────────────────────────────────────────────
# rules
# ──────────────────────────────────────────────────────────────
def _xe_001_multi_estate_writers(graph: Graph, link_result: Dict[str, Any]
                                 ) -> List[Dict[str, Any]]:
    """One table, two or more estates writing it, two or more release trains."""
    out = []
    for label in ('DbTable', 'DbView', 'DbMaterializedView'):
        for table in graph.by_label(label):
            by_estate = _writer_estates(graph, table.node_id)
            if len(by_estate) < 2:
                continue
            detail = '; '.join(
                f"{estate}: {', '.join(sorted({_describe(graph, w) for w in writers}))}"
                for estate, writers in sorted(by_estate.items()))
            out.append(_finding(
                'XE-001', 'HIGH', table.node_id,
                f'{table.name}: written by {len(by_estate)} estates - {detail}',
                'Decide which estate owns this table before either is migrated. '
                'Two writers on separate release trains cannot be cut over '
                'independently, and the second cutover will silently depend on '
                'the first.',
                by_estate))
    return out


def _xe_002_unmodelled_table(graph: Graph, link_result: Dict[str, Any]
                             ) -> List[Dict[str, Any]]:
    """TIBCO names a table no database estate models."""
    out = []
    seen: Set[str] = set()
    for row in link_result.get('unbound', []):
        if row.get('reason') not in ('no-such-object', 'ambiguous-name'):
            continue
        target = row.get('activityId', '')
        key = f"{target}:{row.get('table', '')}"
        if not target or key in seen:
            continue
        seen.add(key)
        out.append(_finding(
            'XE-002', 'HIGH', target,
            f"{row.get('activity', '')}: reaches \"{row.get('table', '')}\", which "
            f'no analysed database estate defines - {row.get("detail", "")}',
            'Either the table lives in a schema outside this analysis, or the '
            'datasource is mapped to the wrong schema. Extend the Oracle '
            'analysis to that schema, or correct the estate map. Until then '
            'this dependency is invisible to every impact assessment.',
            ['tibco']))
    return out


def _xe_003_transaction_boundary(graph: Graph, link_result: Dict[str, Any]
                                 ) -> List[Dict[str, Any]]:
    """A table written from TIBCO and by Oracle code that commits.

    The integration cannot see the database's transaction boundary, so a
    commit inside the Oracle unit makes a partial state visible to TIBCO --
    and makes the failure mode depend on timing rather than on logic.
    """
    out = []
    tibco_written = _tables_written_by(graph, 'tibco')
    for table_id, activities in sorted(tibco_written.items()):
        table = graph.nodes.get(table_id)
        if table is None:
            continue
        committers: Set[str] = set()
        for writer in _accessors(graph, table_id, WRITE_RELS):
            if _estate_of(writer) != 'oracle':
                continue
            if writer.properties.get('hasCommit'):
                committers.add(_describe(graph, writer))
            for owner in _executors(graph, writer.node_id):
                if owner.properties.get('hasCommit'):
                    committers.add(owner.name)
        if not committers:
            continue
        who = ', '.join(sorted(committers))
        via = ', '.join(sorted({_describe(graph, a) for a in activities}))
        out.append(_finding(
            'XE-003', 'HIGH', table_id,
            f'{table.name}: written from TIBCO ({via}) and by Oracle code that '
            f'commits ({who})',
            'Establish who owns the transaction boundary for this table. An '
            'intermediate COMMIT makes partial state visible to the '
            'integration, so a TIBCO retry can act on a half-finished unit of '
            'work. Move the commit to the caller, or make the integration '
            'idempotent for this table.',
            ['tibco', 'oracle']))
    return out


def _xe_004_duplicate_statement(graph: Graph, link_result: Dict[str, Any]
                                ) -> List[Dict[str, Any]]:
    """The same statement digest in two estates: one behaviour, two owners."""
    by_digest: Dict[str, List[GraphNode]] = defaultdict(list)
    for node in graph.nodes.values():
        source_id = str(node.properties.get('sourceNodeId', '') or '')
        if not any(source_id.startswith(prefix) for prefix in CONTENT_ID_PREFIXES):
            continue
        by_digest[source_id].append(node)

    out = []
    for digest, nodes in sorted(by_digest.items()):
        estates = {_estate_of(node) for node in nodes if _estate_of(node)}
        if len(estates) < 2:
            continue
        primary = sorted(nodes, key=lambda n: n.node_id)[0]
        out.append(_finding(
            'XE-004', 'MEDIUM', primary.node_id,
            f'{primary.name}: the same statement ({digest}) is implemented in '
            f"{', '.join(sorted(estates))}",
            'One behaviour with two owners drifts. Decide which estate owns the '
            'statement and have the other call it, or record deliberately that '
            'the duplication is accepted and why.',
            estates))
    return out


def _xe_005_unmapped_datasource(graph: Graph, link_result: Dict[str, Any]
                                ) -> List[Dict[str, Any]]:
    """A JDBC resource with no estate-map entry: everything behind it is dark."""
    out = []
    for record in link_result.get('datasources', []):
        if record.get('mapped'):
            continue
        note = f" - {record['note']}" if record.get('note') else ''
        out.append(_finding(
            'XE-005', 'MEDIUM', record['nodeId'],
            f"{record['name']}: no estate-map entry, so every table reached "
            f'through it stays unbound{note}',
            'Add the resource to the estate map with the Oracle schema it '
            'serves. A JDBC url names a database, not a schema, so this cannot '
            'be inferred - and without it the activities behind this resource '
            'are missing from every blast radius.',
            ['tibco']))
    return out


def _xe_006_runtime_sql_at_the_boundary(graph: Graph, link_result: Dict[str, Any]
                                        ) -> List[Dict[str, Any]]:
    """A JDBC activity that builds its statement at runtime."""
    out = []
    for row in link_result.get('unbound', []):
        if row.get('reason') != 'no-static-sql':
            continue
        target = row.get('activityId', '')
        if not target:
            continue
        out.append(_finding(
            'XE-006', 'MEDIUM', target,
            f"{row.get('activity', '')}: carries no static SQL, so the tables it "
            f'touches cannot be resolved and it appears in no data lineage',
            'Confirm by hand which tables this activity reaches and record it, '
            'or replace the runtime statement with a static one. Do not read '
            'its absence from the lineage as evidence that it touches nothing.',
            ['tibco']))
    return out


def _xe_007_user_surface_over_integrated_table(graph: Graph,
                                               link_result: Dict[str, Any]
                                               ) -> List[Dict[str, Any]]:
    """An APEX page reporting over a table an integration writes behind it."""
    out = []
    tibco_written = _tables_written_by(graph, 'tibco')
    for table_id, activities in sorted(tibco_written.items()):
        table = graph.nodes.get(table_id)
        if table is None:
            continue
        pages: Dict[str, GraphNode] = {}
        for reader in _accessors(graph, table_id, READ_RELS):
            if _estate_of(reader) != 'apex':
                continue
            page = _apex_page_of(graph, reader.node_id)
            if page is not None:
                pages[page.node_id] = page
        if not pages:
            continue
        via = ', '.join(sorted({_describe(graph, a) for a in activities}))
        for page in pages.values():
            out.append(_finding(
                'XE-007', 'HIGH', page.node_id,
                f'{page.name}: reports over {table.name}, which TIBCO writes '
                f'({via}) - the page shows state no APEX code produced',
                'Include this page in the regression scope for any change to '
                'the integration, and confirm the page tolerates the row shape '
                'and the timing the integration produces. A defect here looks '
                'like an APEX defect and is not one.',
                ['tibco', 'apex']))
    return out
