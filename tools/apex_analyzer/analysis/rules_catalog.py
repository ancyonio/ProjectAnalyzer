"""Deterministic rule catalogue (specification §12).

These rules run in the analyzer, not in an agent, and produce `:Issue` nodes
with `origin:'derived'` and `confidence:1.0`. The agent's job is to explain,
prioritise and propose — not to re-detect what a rule already found.

Every rule cites the node and the evidence that triggered it, so a finding can
always be traced back to a component and a line of an export file.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from analyzer_core.ids import issue_id, recommendation_id
from analyzer_core.model import Graph, GraphNode, GraphRel
from analyzer_core.utils import one_line

from .traverse import DEPENDENCY_RELS, ascend, descend, owning_page

# A rule returns (target node, message, [secondary affected node ids])
Finding = Tuple[GraphNode, str, List[str]]


@dataclass
class Rule:
    rule_id: str
    category: str
    severity: str
    title: str
    recommendation: str
    effort: str
    evaluate: Callable[[Graph], Iterable[Finding]]


# ── security ──────────────────────────────────────────────────────────
def _sec_001(graph: Graph) -> Iterable[Finding]:
    for block in graph.by_label('PlsqlBlock'):
        if block.properties.get('dynamicSqlConcatenatesInput'):
            yield (block, 'builds dynamic SQL by concatenating user-controllable '
                          'input (page item or bind)', [])


def _sec_002(graph: Graph) -> Iterable[Finding]:
    for page in graph.by_label('ApexPage'):
        if _has_out(graph, page, 'SECURED_BY'):
            continue
        writes = _write_targets_of_page(graph, page)
        if writes:
            names = sorted({graph.node(t).name for t in writes if graph.node(t)})
            yield (page, f'has no authorization scheme but writes to '
                         f'{", ".join(names[:5])}', sorted(writes))


def _sec_003(graph: Graph) -> Iterable[Finding]:
    for page in graph.by_label('ApexPage'):
        if str(page.properties.get('pageAccessProtection', '')).upper() != 'UNRESTRICTED':
            continue
        unprotected = [item for item in _components(graph, page, 'ApexItem')
                       if str(item.properties.get('sessionStateProtection', '')).upper()
                       in ('NONE', 'UNRESTRICTED', '')]
        if unprotected:
            yield (page, f'page access is unrestricted and {len(unprotected)} item(s) '
                         f'have no session state protection',
                   [i.node_id for i in unprotected[:20]])


def _sec_004(graph: Graph) -> Iterable[Finding]:
    for page in graph.by_label('ApexPage'):
        if not page.properties.get('isPublic'):
            continue
        if page.properties.get('pageId') in (101,):      # the login page
            continue
        reach = descend(graph, page.node_id, max_depth=8)
        tables = [graph.node(n) for n in reach
                  if graph.node(n) and graph.node(n).label in ('DbTable', 'DbView')]
        if tables:
            yield (page, f'is publicly reachable and queries '
                         f'{", ".join(sorted({t.name for t in tables})[:5])}',
                   [t.node_id for t in tables[:20]])


def _sec_005(graph: Graph) -> Iterable[Finding]:
    for item in graph.by_label('ApexItem'):
        protection = str(item.properties.get('sessionStateProtection', '')).upper()
        if protection not in ('NONE', 'UNRESTRICTED', ''):
            continue
        for rel in graph.outgoing(item.node_id):
            if rel.rel_type != 'REFERENCES_COLUMN':
                continue
            column = graph.node(rel.end_id)
            if column is not None and column.properties.get('isPk'):
                yield (item, f'holds primary key column {column.name} with no session '
                             f'state protection', [column.node_id])
                break


def _sec_006(graph: Graph) -> Iterable[Finding]:
    for scheme in graph.by_label('ApexAuthorization'):
        if not any(r.rel_type == 'SECURED_BY' for r in graph.incoming(scheme.node_id)):
            yield (scheme, 'is defined but not applied to any component', [])


def _sec_007(graph: Graph) -> Iterable[Finding]:
    for statement in graph.by_label('SqlStatement'):
        text = str(statement.properties.get('text', ''))
        if '&' in text and '.' in text and _has_substitution(text):
            owners = [graph.node(r.start_id).name
                      for r in graph.incoming(statement.node_id)
                      if r.rel_type == 'EXECUTES_SQL' and graph.node(r.start_id)]
            yield (statement, f'uses `&ITEM.` substitution rather than a `:ITEM` bind '
                              f'({", ".join(owners[:3]) or "unattached"})', [])


def _sec_008(graph: Graph) -> Iterable[Finding]:
    markers = ('PASSWORD', 'SECRET', 'TOKEN', 'APIKEY', 'API_KEY', 'CREDENTIAL')
    for item in graph.by_label('ApexItem'):
        name = str(item.properties.get('itemName', '')).upper()
        if any(marker in name for marker in markers):
            yield (item, 'holds credential-shaped session state; confirm it is never '
                         'persisted or logged', [])


# ── performance ───────────────────────────────────────────────────────
def _perf_001(graph: Graph) -> Iterable[Finding]:
    for statement in graph.by_label('SqlStatement'):
        if not statement.properties.get('hasSelectStar'):
            continue
        for rel in graph.incoming(statement.node_id):
            region = graph.node(rel.start_id)
            if rel.rel_type == 'EXECUTES_SQL' and region and region.label == 'ApexRegion':
                yield (region, 'region source uses SELECT *; column changes will break '
                               'the report', [statement.node_id])
                break


def _perf_002(graph: Graph) -> Iterable[Finding]:
    for column in graph.by_label('ApexReportColumn'):
        for rel in graph.outgoing(column.node_id):
            if rel.rel_type != 'USES_LOV':
                continue
            lov = graph.node(rel.end_id)
            if lov is not None and str(lov.properties.get('lovType', '')).upper() == 'DYNAMIC':
                yield (column, f'renders through dynamic LOV "{lov.name}", which runs '
                               f'a query per row', [lov.node_id])


def _perf_003(graph: Graph) -> Iterable[Finding]:
    for region in graph.by_label('ApexRegion'):
        if str(region.properties.get('regionType', '')) not in (
                'CLASSIC_REPORT', 'INTERACTIVE_REPORT', 'INTERACTIVE_GRID'):
            continue
        for node_id in descend(graph, region.node_id, max_depth=3):
            table = graph.node(node_id)
            if table is None or table.label != 'DbTable':
                continue
            rows = int(table.properties.get('numRows', 0) or 0)
            if rows > 100_000:
                yield (region, f'reports over {table.name} ({rows:,} rows); confirm '
                               f'pagination and a driving index', [table.node_id])
                break


def _perf_004(graph: Graph) -> Iterable[Finding]:
    for statement in graph.by_label('SqlStatement'):
        joins = int(statement.properties.get('joinCount', 0) or 0)
        if joins >= 5 and int(statement.properties.get('bindCount', 0) or 0) == 0:
            yield (statement, f'joins {joins} sources with no bind-variable predicate',
                   [])


def _perf_005(graph: Graph) -> Iterable[Finding]:
    for statement in graph.by_label('SqlStatement'):
        if statement.properties.get('hasHint'):
            yield (statement, 'carries a hardcoded optimizer hint', [])


def _perf_006(graph: Graph) -> Iterable[Finding]:
    for statement in graph.by_label('SqlStatement'):
        users = [r for r in graph.incoming(statement.node_id)
                 if r.rel_type == 'EXECUTES_SQL']
        if len(users) >= 5:
            yield (statement, f'is executed by {len(users)} components; extract it to a '
                              f'view or a shared LOV', [r.start_id for r in users[:20]])


def _perf_008(graph: Graph) -> Iterable[Finding]:
    for statement in graph.by_label('SqlStatement'):
        if statement.properties.get('hasDbLink'):
            yield (statement, 'crosses a database link during page rendering', [])


# ── correctness and debt ──────────────────────────────────────────────
def _corr_003(graph: Graph) -> Iterable[Finding]:
    for block in graph.by_label('PlsqlBlock'):
        if block.properties.get('hasWhenOthersNull'):
            yield (block, 'swallows every exception with WHEN OTHERS THEN NULL', [])


def _corr_004(graph: Graph) -> Iterable[Finding]:
    for block in graph.by_label('PlsqlBlock'):
        if not block.properties.get('hasCommit'):
            continue
        owners = [graph.node(r.start_id) for r in graph.incoming(block.node_id)
                  if r.rel_type == 'EXECUTES_PLSQL']
        if any(o is not None and o.label in ('ApexProcess', 'ApexDaAction')
               for o in owners):
            yield (block, 'commits inside a page process, which breaks APEX '
                          'transaction handling and error recovery', [])


def _corr_006(graph: Graph) -> Iterable[Finding]:
    for button in graph.by_label('ApexButton'):
        if str(button.properties.get('action', '')).upper() != 'SUBMIT':
            continue
        if any(r.rel_type == 'TRIGGERS' for r in graph.outgoing(button.node_id)):
            continue
        yield (button, 'submits the page but no process, validation or branch is '
                       'conditioned on it', [])


def _debt_001(graph: Graph) -> Iterable[Finding]:
    for page in graph.by_label('ApexPage'):
        page_number = page.properties.get('pageId')
        if page_number in (0, 1, 101):
            continue
        if str(page.properties.get('pageMode', '')).upper() in ('MODAL', 'NON_MODAL'):
            pass    # modal pages still need an inbound link to be reachable
        if any(r.rel_type == 'NAVIGATES_TO' for r in graph.incoming(page.node_id)):
            continue
        yield (page, 'has no inbound navigation: no branch, button, list entry or '
                     'navigation bar entry targets it', [])


def _debt_002(graph: Graph) -> Iterable[Finding]:
    for label, relation in (('ApexLov', 'USES_LOV'), ('ApexList', 'CONTAINS_ITEM')):
        for node in graph.by_label(label):
            if label == 'ApexLov' and not any(r.rel_type == relation
                                              for r in graph.incoming(node.node_id)):
                yield (node, 'is defined but no item or report column uses it', [])


def _debt_003(graph: Graph) -> Iterable[Finding]:
    excluded = {option.node_id for option in graph.by_label('ApexBuildOption')
                if str(option.properties.get('status', '')).upper() in
                ('EXCLUDE', 'EXCLUDED')}
    if not excluded:
        return
    for rel in graph.rels:
        if rel.rel_type == 'CONDITIONED_BY' and rel.end_id in excluded:
            node = graph.node(rel.start_id)
            option = graph.node(rel.end_id)
            if node is not None and option is not None:
                yield (node, f'is permanently disabled by build option '
                             f'"{option.name}"', [option.node_id])


def _debt_004(graph: Graph) -> Iterable[Finding]:
    for block in graph.by_label('PlsqlBlock'):
        deprecated = block.properties.get('deprecatedCalls')
        if deprecated:
            yield (block, f'calls deprecated APEX APIs: {deprecated}', [])
    for region in graph.by_label('ApexRegion'):
        if str(region.properties.get('regionType', '')) == 'TABULAR_FORM':
            yield (region, 'is a legacy tabular form; migrate to an interactive grid',
                   [])


def _debt_005(graph: Graph) -> Iterable[Finding]:
    for snippet in graph.by_label('JsSnippet'):
        if int(snippet.properties.get('lineCount', 0) or 0) > 40:
            yield (snippet, f'is {snippet.properties.get("lineCount")} lines of inline '
                            f'JavaScript; move it to a static application file', [])


def _debt_006(graph: Graph) -> Iterable[Finding]:
    for block in graph.by_label('PlsqlBlock'):
        users = [r for r in graph.incoming(block.node_id)
                 if r.rel_type == 'EXECUTES_PLSQL']
        if len(users) >= 3:
            yield (block, f'is duplicated across {len(users)} components; extract it '
                          f'into a package', [r.start_id for r in users[:20]])


RULES: List[Rule] = [
    Rule('SEC-001', 'SECURITY', 'CRITICAL', 'SQL injection through dynamic SQL',
         'Replace concatenation with bind variables, or validate through '
         'DBMS_ASSERT before assembling the statement.', 'M', _sec_001),
    Rule('SEC-002', 'SECURITY', 'HIGH', 'Unsecured page performs DML',
         'Attach an authorization scheme to the page, or to each process that '
         'writes.', 'S', _sec_002),
    Rule('SEC-003', 'SECURITY', 'HIGH', 'Unrestricted page access with unprotected items',
         'Set page access protection to "Arguments Must Have Checksum" and give '
         'key items session state protection.', 'S', _sec_003),
    Rule('SEC-004', 'SECURITY', 'HIGH', 'Public page queries application data',
         'Confirm the page is intended to be public and that its query is scoped '
         'to data safe for anonymous users.', 'M', _sec_004),
    Rule('SEC-005', 'SECURITY', 'MEDIUM', 'Primary key item is tamperable',
         'Set session state protection to "Checksum Required" on key items.',
         'S', _sec_005),
    Rule('SEC-006', 'SECURITY', 'MEDIUM', 'Unused authorization scheme',
         'Apply the scheme or delete it; an unused scheme suggests a control that '
         'was intended but never wired up.', 'S', _sec_006),
    Rule('SEC-007', 'SECURITY', 'MEDIUM', 'Substitution string in SQL',
         'Use `:ITEM` bind syntax so the value is bound, not inlined.', 'S', _sec_007),
    Rule('SEC-008', 'SECURITY', 'LOW', 'Credential-shaped session state',
         'Hold secrets in a credential store, not in session state.', 'M', _sec_008),

    Rule('PERF-001', 'PERFORMANCE', 'HIGH', 'SELECT * in a region source',
         'Name the columns the region actually renders.', 'S', _perf_001),
    Rule('PERF-002', 'PERFORMANCE', 'HIGH', 'Per-row LOV query in a report',
         'Join the lookup into the report query, or switch the column to a shared '
         'static LOV.', 'M', _perf_002),
    Rule('PERF-003', 'PERFORMANCE', 'HIGH', 'Report over a large table',
         'Confirm pagination is bounded and the driving predicate is indexed.',
         'M', _perf_003),
    Rule('PERF-004', 'PERFORMANCE', 'MEDIUM', 'Wide join with no bound predicate',
         'Add a bind-variable predicate, or move the query behind a view with a '
         'driving filter.', 'M', _perf_004),
    Rule('PERF-005', 'PERFORMANCE', 'MEDIUM', 'Hardcoded optimizer hint',
         'Remove the hint and fix the underlying statistics or index.', 'M', _perf_005),
    Rule('PERF-006', 'PERFORMANCE', 'MEDIUM', 'Duplicated SQL statement',
         'Extract the query into a database view or a shared component.', 'M', _perf_006),
    Rule('PERF-008', 'PERFORMANCE', 'MEDIUM', 'Database link used during rendering',
         'Cache or materialise the remote data; a remote call on the render path '
         'makes page latency depend on another database.', 'L', _perf_008),

    Rule('CORR-003', 'CORRECTNESS', 'HIGH', 'Exception silently swallowed',
         'Log the error and re-raise, or handle the specific exception.', 'S', _corr_003),
    Rule('CORR-004', 'CORRECTNESS', 'MEDIUM', 'COMMIT inside a page process',
         'Let APEX manage the transaction; remove the explicit COMMIT.', 'S', _corr_004),
    Rule('CORR-006', 'CORRECTNESS', 'MEDIUM', 'Submit button reaches nothing',
         'Condition a process on the button, or change it to a redirect.', 'S', _corr_006),

    Rule('DEBT-001', 'TECH_DEBT', 'MEDIUM', 'Unreachable page',
         'Delete the page, or add the navigation that was intended.', 'S', _debt_001),
    Rule('DEBT-002', 'TECH_DEBT', 'LOW', 'Unused shared component',
         'Delete it, or wire it up.', 'S', _debt_002),
    Rule('DEBT-003', 'TECH_DEBT', 'LOW', 'Component disabled by a build option',
         'Remove the component and the build option once the feature decision is '
         'final.', 'S', _debt_003),
    Rule('DEBT-004', 'TECH_DEBT', 'MEDIUM', 'Deprecated component or API in use',
         'Migrate to the supported equivalent before the next APEX upgrade.',
         'M', _debt_004),
    Rule('DEBT-005', 'MAINTAINABILITY', 'LOW', 'Large inline JavaScript block',
         'Move the code into a static application file so it can be cached, '
         'linted and reviewed.', 'S', _debt_005),
    Rule('DEBT-006', 'MAINTAINABILITY', 'MEDIUM', 'Duplicated PL/SQL block',
         'Extract the logic into a package procedure and call it from each '
         'component.', 'M', _debt_006),
]

# Findings raised during parsing rather than by a graph rule.
PARSE_TIME_RULES: Dict[str, Tuple[str, str, str, str]] = {
    'CORR-001': ('CORRECTNESS', 'HIGH', 'Reference to a missing database object',
                 'Add the object to the database extract, or fix the reference; '
                 'until then every impact answer through this component is '
                 'incomplete.'),
    'CORR-002': ('CORRECTNESS', 'HIGH', 'Item sourced from a missing column',
                 'Repoint the item at an existing column, or restore the column.'),
    'CORR-005': ('CORRECTNESS', 'MEDIUM', 'Branch targets a page that does not exist',
                 'Fix the branch target; the user hits a "page not found" error.'),
}


def run_rules(graph: Graph, resolver=None,
              parse_findings: Optional[List[Dict[str, str]]] = None,
              dataset_id: str = '') -> int:
    """Evaluate every rule and add `:Issue` / `:Recommendation` nodes."""
    added = 0
    for rule in RULES:
        try:
            findings = list(rule.evaluate(graph))
        except Exception:                       # a broken rule must not stop the rest
            continue
        for node, message, affected in findings:
            added += _add_issue(graph, rule.rule_id, rule.category, rule.severity,
                                rule.title, f'{node.name}: {message}', node,
                                affected, rule.recommendation, rule.effort, dataset_id)

    for finding in parse_findings or []:
        rule_id = finding['ruleId']
        category, severity, title, recommendation = PARSE_TIME_RULES.get(
            rule_id, ('CORRECTNESS', 'MEDIUM', rule_id, 'Investigate.'))
        node = graph.node(finding['nodeId'])
        if node is None:
            continue
        added += _add_issue(graph, rule_id, category, severity, title,
                            f"{node.name}: {finding['message']}", node, [],
                            recommendation, 'M', dataset_id)

    graph.reindex()
    return added


def _add_issue(graph: Graph, rule_id: str, category: str, severity: str, title: str,
               description: str, node: GraphNode, affected: List[str],
               recommendation: str, effort: str, dataset_id: str) -> int:
    node_id = issue_id(rule_id, node.node_id)
    if node_id in graph.nodes:
        return 0
    page = owning_page(graph, node.node_id)
    properties: Dict[str, Any] = {
        'ruleId': rule_id,
        'category': category,
        'severity': severity,
        'title': title,
        'description': one_line(description, 400),
        'confidence': 1.0,
        'origin': 'derived',
        'evidence': node.node_id,
        'targetLabel': node.label,
        'sourceFile': node.properties.get('sourceFile', ''),
        'datasetId': dataset_id,
    }
    # typed columns must stay typed: omit rather than write an empty string
    page_id = (page.properties.get('pageId') if page
               else node.properties.get('pageId'))
    if isinstance(page_id, int):
        properties['pageId'] = page_id
    source_line = node.properties.get('sourceLine')
    if isinstance(source_line, int):
        properties['sourceLine'] = source_line
    graph.nodes[node_id] = GraphNode(node_id, 'Issue', f'{rule_id} {title}',
                                     {k: v for k, v in properties.items() if v != ''})
    graph.rels.append(GraphRel(node.node_id, node_id, 'HAS_ISSUE', {'origin': 'derived'}))
    for affected_id in affected[:20]:
        if affected_id in graph.nodes and affected_id != node.node_id:
            graph.rels.append(GraphRel(node_id, affected_id, 'AFFECTS',
                                       {'origin': 'derived'}))

    rec_id = recommendation_id(node_id)
    graph.nodes[rec_id] = GraphNode(rec_id, 'Recommendation', f'Fix {rule_id}', {
        'title': title,
        'action': recommendation,
        'effort': effort,
        'rationale': one_line(description, 300),
        'origin': 'derived',
        'confidence': 1.0,
        'datasetId': dataset_id,
    })
    graph.rels.append(GraphRel(node_id, rec_id, 'HAS_RECOMMENDATION',
                               {'origin': 'derived'}))
    return 1


# ── helpers ───────────────────────────────────────────────────────────
def _has_out(graph: Graph, node: GraphNode, rel_type: str) -> bool:
    return any(r.rel_type == rel_type for r in graph.outgoing(node.node_id))


def _components(graph: Graph, page: GraphNode, label: str) -> List[GraphNode]:
    return [graph.node(n) for n in descend(graph, page.node_id, max_depth=4)
            if graph.node(n) is not None and graph.node(n).label == label]


def _write_targets_of_page(graph: Graph, page: GraphNode) -> List[str]:
    from .traverse import WRITE_RELS
    reach = descend(graph, page.node_id, max_depth=8)
    targets = []
    for node_id in list(reach) + [page.node_id]:
        for rel in graph.outgoing(node_id):
            if rel.rel_type in WRITE_RELS:
                targets.append(rel.end_id)
    return sorted(set(targets))


def _has_substitution(text: str) -> bool:
    import re
    from ..constants import SUBSTITUTION_RE
    for match in SUBSTITUTION_RE.finditer(text):
        name = match.group(1).upper()
        if name not in ('APP_ID', 'SESSION', 'DEBUG', 'REQUEST', 'APP_USER',
                        'APP_PAGE_ID', 'HOST_URL', 'IMAGE_PREFIX'):
            return True
    return False
