"""The rule catalogue.

Every rule reads only what the parsers established, so a finding can always be
traced to a node and a line. Findings become `Issue` nodes with a
`Recommendation`, using the same shape as the APEX catalogue -- one label with
a `category`, not a label per finding type.

Rule ids are stable: `SEC`, `PERF`, `CORR`, `DEBT` plus an ordinal. Adding a
rule takes the next free ordinal; ids are never reused.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from analyzer_core.ids import issue_id, recommendation_id
from analyzer_core.model import GraphNode

from ..constants import CREDENTIAL_HINTS

# A literal password in source, as opposed to a bind or a lookup.
_CREDENTIAL_RE = re.compile(
    r'\b(' + '|'.join(CREDENTIAL_HINTS) + r')\b\s*(:=|=>|=)\s*\'[^\']{3,}\'',
    re.IGNORECASE)

# Rows a table needs before a full scan of it is worth reporting.
_LARGE_TABLE_ROWS = 100_000


def apply_rules(analyzer) -> int:
    """Run every rule and attach the findings it produces."""
    findings: List[Dict[str, Any]] = []
    for rule in (_sec_001_dynamic_sql, _sec_002_hardcoded_credential,
                 _corr_001_when_others_null, _corr_002_commit_in_trigger,
                 _corr_003_unbounded_dml, _perf_001_select_star,
                 _perf_002_optimizer_hint, _perf_003_large_table_scan,
                 _debt_001_missing_body, _debt_002_uncalled_unit,
                 _debt_003_invalid_object, _debt_004_unresolved):
        findings.extend(rule(analyzer) or [])

    for finding in findings:
        _attach(analyzer, finding)
    return len(findings)


def _finding(rule_id: str, severity: str, category: str, target: str,
             description: str, recommendation: str) -> Dict[str, Any]:
    return {
        'ruleId': rule_id, 'severity': severity, 'category': category,
        'target': target, 'description': description,
        'recommendation': recommendation,
    }


def _locate(analyzer, target: str) -> Dict[str, Any]:
    """File and line for a finding.

    A SqlStatement is content-addressed and has no file of its own, so fall
    back to whichever unit executes it -- otherwise the finding names a
    problem the analyst cannot go and look at.
    """
    node = analyzer.nodes[target]
    if node.properties.get('filePath'):
        return {'filePath': node.properties['filePath'],
                'lineStart': node.properties.get('lineStart', 0)}
    for rel in analyzer.rels:
        if rel.rel_type == 'EXECUTES_SQL' and rel.end_id == target:
            owner = analyzer.nodes.get(rel.start_id)
            if owner is not None and owner.properties.get('filePath'):
                return {'filePath': owner.properties['filePath'],
                        'lineStart': owner.properties.get('lineStart', 0)}
    return {'filePath': '', 'lineStart': 0}


def _attach(analyzer, finding: Dict[str, Any]) -> None:
    target = finding['target']
    if target not in analyzer.nodes:
        return
    location = _locate(analyzer, target)
    node_id = issue_id(finding['ruleId'], target)
    if node_id in analyzer.nodes:
        return
    analyzer._add_node(GraphNode(node_id, 'Issue', finding['ruleId'], {
        'ruleId': finding['ruleId'],
        'severity': finding['severity'],
        'category': finding['category'],
        'description': finding['description'],
        'targetLabel': analyzer.nodes[target].label,
        'targetName': analyzer.nodes[target].name,
        'filePath': location['filePath'],
        'lineStart': location['lineStart'],
    }))
    analyzer._add_rel(target, node_id, 'HAS_ISSUE', purpose='rule-finding')
    analyzer._add_rel(node_id, target, 'AFFECTS', purpose='finding-target')

    rec_id = recommendation_id(node_id)
    analyzer._add_node(GraphNode(rec_id, 'Recommendation', finding['ruleId'], {
        'text': finding['recommendation'],
        'ruleId': finding['ruleId'],
        'severity': finding['severity'],
    }))
    analyzer._add_rel(node_id, rec_id, 'HAS_RECOMMENDATION',
                      purpose='remediation')


# ── security ──────────────────────────────────────────────────────────
def _sec_001_dynamic_sql(analyzer) -> List[Dict[str, Any]]:
    out = []
    for node in analyzer.nodes.values():
        if node.label != 'DbProgramUnit':
            continue
        if not node.properties.get('hasDynamicSql'):
            continue
        out.append(_finding(
            'SEC-001', 'CRITICAL', 'SECURITY', node.node_id,
            f'{node.name}: builds SQL at runtime, so its dependencies cannot be '
            f'resolved statically and its inputs may not be bound',
            'Replace EXECUTE IMMEDIATE with static SQL, or bind every '
            'user-supplied value with USING rather than concatenating it.'))
    return out


def _sec_002_hardcoded_credential(analyzer) -> List[Dict[str, Any]]:
    out = []
    for source in analyzer.sources:
        if not _CREDENTIAL_RE.search(source.text):
            continue
        out.append(_finding(
            'SEC-002', 'HIGH', 'SECURITY', source.node_id,
            f'{source.rel_path}: assigns a credential from a literal in source',
            'Move the secret to a wallet, a vault or an environment-supplied '
            'parameter. The value is not copied into this graph.'))
    return out


# ── correctness ───────────────────────────────────────────────────────
def _corr_001_when_others_null(analyzer) -> List[Dict[str, Any]]:
    out = []
    for node in analyzer.nodes.values():
        if node.label == 'DbProgramUnit' and node.properties.get('hasWhenOthersNull'):
            out.append(_finding(
                'CORR-001', 'HIGH', 'CORRECTNESS', node.node_id,
                f'{node.name}: swallows every exception with WHEN OTHERS THEN NULL',
                'Handle the exceptions you expect and re-raise the rest, so a '
                'failure surfaces instead of silently returning success.'))
    return out


def _corr_002_commit_in_trigger(analyzer) -> List[Dict[str, Any]]:
    out = []
    for node in analyzer.nodes.values():
        if node.label == 'DbTrigger' and node.properties.get('hasCommit'):
            out.append(_finding(
                'CORR-002', 'HIGH', 'CORRECTNESS', node.node_id,
                f'{node.name}: commits inside a trigger, which breaks the '
                f'calling transaction and can raise ORA-04092',
                'Remove the COMMIT, or move the work to an autonomous '
                'transaction only if the side effect is genuinely independent.'))
    return out


def _corr_003_unbounded_dml(analyzer) -> List[Dict[str, Any]]:
    out = []
    for node in analyzer.nodes.values():
        if node.label != 'SqlStatement' or not node.properties.get('hasNoWhere'):
            continue
        out.append(_finding(
            'CORR-003', 'HIGH', 'CORRECTNESS', node.node_id,
            f'{node.properties.get("verb", "DML")} statement has no WHERE '
            f'clause and therefore affects every row',
            'Confirm the statement is meant to affect the whole table; if not, '
            'add the predicate that bounds it.'))
    return out


# ── performance ───────────────────────────────────────────────────────
def _perf_001_select_star(analyzer) -> List[Dict[str, Any]]:
    out = []
    for node in analyzer.nodes.values():
        if node.label == 'SqlStatement' and node.properties.get('hasSelectStar'):
            out.append(_finding(
                'PERF-001', 'MEDIUM', 'PERFORMANCE', node.node_id,
                'Query uses SELECT *; a column added to the table silently '
                'changes what this returns',
                'Name the columns the caller actually needs.'))
    return out


def _perf_002_optimizer_hint(analyzer) -> List[Dict[str, Any]]:
    out = []
    for node in analyzer.nodes.values():
        if node.label == 'SqlStatement' and node.properties.get('hasHint'):
            out.append(_finding(
                'PERF-002', 'MEDIUM', 'PERFORMANCE', node.node_id,
                'Query carries a hardcoded optimizer hint, which pins a plan '
                'that may not survive a statistics or version change',
                'Remove the hint and confirm the plan with current statistics; '
                'keep it only with a recorded reason.'))
    return out


def _perf_003_large_table_scan(analyzer) -> List[Dict[str, Any]]:
    """Only fires with a dictionary extract: row counts come from there."""
    out = []
    for rel in analyzer.rels:
        if rel.rel_type != 'READS_FROM':
            continue
        table = analyzer.nodes.get(rel.end_id)
        statement = analyzer.nodes.get(rel.start_id)
        if table is None or statement is None:
            continue
        rows = table.properties.get('numRows') or 0
        if rows < _LARGE_TABLE_ROWS:
            continue
        if not statement.properties.get('hasSelectStar') and \
                not statement.properties.get('hasNoWhere'):
            continue
        out.append(_finding(
            'PERF-003', 'HIGH', 'PERFORMANCE', rel.start_id,
            f'Unbounded read of {table.name} ({rows:,} rows)',
            f'Add a predicate that uses an index on {table.name}, or paginate '
            f'the result.'))
    return out


# ── debt ──────────────────────────────────────────────────────────────
def _debt_001_missing_body(analyzer) -> List[Dict[str, Any]]:
    out = []
    for node in analyzer.nodes.values():
        if node.label != 'DbPackage':
            continue
        halves = {analyzer.nodes[r.end_id].label
                  for r in analyzer.rels
                  if r.start_id == node.node_id
                  and r.rel_type in ('HAS_SPEC', 'HAS_BODY')
                  and r.end_id in analyzer.nodes}
        if 'PackageSpec' in halves and 'PackageBody' not in halves:
            out.append(_finding(
                'DEBT-001', 'MEDIUM', 'DEBT', node.node_id,
                f'{node.name}: a spec is published but no body was found in '
                f'the analysed tree',
                'Confirm the body is deployed but not in source control, or '
                'that the package is genuinely unimplemented.'))
    return out


def _debt_002_uncalled_unit(analyzer) -> List[Dict[str, Any]]:
    """A unit nothing calls and no spec publishes cannot be reached."""
    called = {r.end_id for r in analyzer.rels if r.rel_type == 'CALLS'}
    published = set()
    for rel in analyzer.rels:
        if rel.rel_type != 'HAS_UNIT':
            continue
        parent = analyzer.nodes.get(rel.start_id)
        if parent is not None and parent.label == 'PackageSpec':
            published.add(rel.end_id)

    out = []
    for node in analyzer.nodes.values():
        if node.label != 'DbProgramUnit' or node.properties.get('declaredOnly'):
            continue
        if node.node_id in called or node.node_id in published:
            continue
        if node.properties.get('isStandalone'):
            continue
        out.append(_finding(
            'DEBT-002', 'LOW', 'DEBT', node.node_id,
            f'{node.name}: private to its package body and never called within '
            f'the analysed tree',
            'Confirm it is dead and remove it, or note the caller the analysis '
            'cannot see (dynamic SQL, an external job).'))
    return out


def _debt_003_invalid_object(analyzer) -> List[Dict[str, Any]]:
    out = []
    for node in analyzer.nodes.values():
        if str(node.properties.get('status', '')).upper() == 'INVALID':
            out.append(_finding(
                'DEBT-003', 'HIGH', 'DEBT', node.node_id,
                f'{node.name}: the database reports this object as INVALID',
                'Recompile it and fix whatever the compilation reports; an '
                'invalid object fails at first use.'))
    return out


def _debt_004_unresolved(analyzer) -> List[Dict[str, Any]]:
    out = []
    for node in analyzer.nodes.values():
        if node.label != 'UnresolvedRef':
            continue
        out.append(_finding(
            'DEBT-004', 'LOW', 'DEBT', node.node_id,
            f'{node.name}: referenced {node.properties.get("referenceCount", 0)} '
            f'time(s) but never defined in the analysed tree',
            'Supply the missing source, or a dictionary extract, before '
            'treating the dependency graph as complete.'))
    return out
