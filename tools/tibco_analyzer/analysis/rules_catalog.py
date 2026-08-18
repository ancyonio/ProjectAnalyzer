"""The TIBCO rule catalogue.

Every rule reads only what the parsers established, so a finding can always be
traced back to a node and a file. Findings become `Issue` nodes with a
`Recommendation`, using the same shape as the APEX and Oracle catalogues -- one
label with a `category`, not a label per finding type -- so one Cypher query
answers all three, and the cross-estate wrapper can merge the ledgers.

Rule ids are stable: `SEC`, `CORR`, `PERF`, `DEBT` plus an ordinal. Adding a
rule takes the next free ordinal; ids are never reused. Note that the same
ordinal means something different in the APEX and Oracle catalogues, which is
why the federated ledger namespaces them (`TIB.SEC-001`).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from analyzer_core.ids import issue_id, recommendation_id
from analyzer_core.model import GraphNode

# A global variable whose *name* says it carries a secret.
_SECRET_NAME_RE = re.compile(r'(password|passwd|secret|credential|apikey|token)',
                             re.IGNORECASE)

# A host that will not exist in any other environment.
_LOCAL_HOST_RE = re.compile(r'\b(localhost|127\.0\.0\.1|::1)\b', re.IGNORECASE)

_SELECT_STAR_RE = re.compile(r'select\s+\*', re.IGNORECASE)

# Activity categories that reach something outside the engine.
_EXTERNAL_CATEGORIES = (
    'JDBC_QUERY', 'JDBC_UPDATE', 'JDBC_GENERAL', 'JDBC_STORED_PROC',
    'HTTP_REQUEST', 'SOAP_CALL', 'JMS_SEND', 'JMS_PUBLISH',
    'JMS_REQUEST_REPLY', 'FTP_PUT', 'FTP_GET', 'MAIL_SEND', 'FILE_WRITE',
    'FILE_READ', 'RV_PUBLISH',
)


def apply_rules(analyzer) -> int:
    """Run every rule and attach the findings it produces."""
    findings: List[Dict[str, Any]] = []
    for rule in (_sec_001_credential_in_resource,
                 _sec_002_secret_global_variable,
                 _sec_003_environment_specific_endpoint,
                 _corr_001_external_call_without_error_handler,
                 _corr_002_no_entry_point,
                 _perf_001_select_star,
                 _debt_001_uncalled_process,
                 _debt_002_unused_shared_resource,
                 _debt_003_unresolved_reference):
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


def _attach(analyzer, finding: Dict[str, Any]) -> None:
    target = finding['target']
    if target not in analyzer.nodes:
        return
    node_id = issue_id(finding['ruleId'], target)
    if node_id in analyzer.nodes:
        return
    node = analyzer.nodes[target]

    analyzer._add_node(GraphNode(node_id, 'Issue', finding['ruleId'], {
        'ruleId': finding['ruleId'],
        'severity': finding['severity'],
        'category': finding['category'],
        'description': finding['description'],
        'targetLabel': node.label,
        'targetName': node.name,
        'module': str(node.properties.get('module', '') or ''),
        'filePath': str(node.properties.get('filePath', '') or ''),
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


# ── helpers ───────────────────────────────────────────────────────────
def _by_label(analyzer, label: str) -> List[GraphNode]:
    return [node for node in analyzer.nodes.values() if node.label == label]


def _process_of(analyzer, activity: GraphNode) -> Optional[GraphNode]:
    ref = activity.properties.get('processRef')
    node = analyzer.nodes.get(ref) if ref else None
    return node if node is not None and node.label == 'BWProcess' else None


def _incoming_types(analyzer, node_id: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for rel in analyzer.rels:
        if rel.end_id == node_id:
            counts[rel.rel_type] = counts.get(rel.rel_type, 0) + 1
    return counts


def _outgoing_types(analyzer, node_id: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for rel in analyzer.rels:
        if rel.start_id == node_id:
            counts[rel.rel_type] = counts.get(rel.rel_type, 0) + 1
    return counts


# ── security ──────────────────────────────────────────────────────────
def _sec_001_credential_in_resource(analyzer) -> List[Dict[str, Any]]:
    """A shared resource carrying a password, obfuscated or not.

    The parser records only that a credential is present, never its value, so
    this rule reads a boolean rather than a secret.
    """
    out = []
    for node in _by_label(analyzer, 'SharedResource'):
        if not node.properties.get('hasEmbeddedCredential'):
            continue
        out.append(_finding(
            'SEC-001', 'HIGH', 'SECURITY', node.node_id,
            f'{node.name}: carries a credential inline in the resource file, '
            f"which is committed to source control (TIBCO's `#!` obfuscation "
            f'is reversible)',
            'Move the credential to a module property supplied at deployment '
            'time, or to the platform credential store. The value is not '
            'copied into this graph.'))
    return out


def _sec_002_secret_global_variable(analyzer) -> List[Dict[str, Any]]:
    """A global variable named like a secret and carrying a default value."""
    out = []
    for node in _by_label(analyzer, 'GlobalVariable'):
        if not _SECRET_NAME_RE.search(node.name):
            continue
        value = str(node.properties.get('value', '') or '')
        if not value.strip():
            continue
        out.append(_finding(
            'SEC-002', 'HIGH', 'SECURITY', node.node_id,
            f'{node.name}: is a secret-named global variable with a default '
            f'value committed alongside the module',
            'Leave the default empty and supply the value per environment, or '
            'mark it service-settable and inject it at deployment.'))
    return out


def _sec_003_environment_specific_endpoint(analyzer) -> List[Dict[str, Any]]:
    """A resource pinned to a host that exists in one environment only."""
    out = []
    for node in _by_label(analyzer, 'SharedResource'):
        endpoint = ' '.join(str(node.properties.get(key, '') or '')
                            for key in ('url', 'host'))
        if not _LOCAL_HOST_RE.search(endpoint):
            continue
        out.append(_finding(
            'SEC-003', 'MEDIUM', 'SECURITY', node.node_id,
            f'{node.name}: points at a developer host ({endpoint.strip()}), so '
            f'the deployed configuration is not the configuration in source',
            'Replace the literal host with a module property, so the same '
            'artefact deploys to every environment and the graph shows the '
            'real dependency.'))
    return out


# ── correctness ───────────────────────────────────────────────────────
def _corr_001_external_call_without_error_handler(analyzer) -> List[Dict[str, Any]]:
    """A process that calls out but catches nothing.

    Anything crossing the process boundary can fail in ways the engine cannot
    retry for you, and an uncaught fault ends the process instance.
    """
    out = []
    for process in _by_label(analyzer, 'BWProcess'):
        if _outgoing_types(analyzer, process.node_id).get('HANDLES_ERROR'):
            continue
        external = sorted({
            str(activity.properties.get('category'))
            for activity in _by_label(analyzer, 'Activity')
            if activity.properties.get('processRef') == process.node_id
            and activity.properties.get('category') in _EXTERNAL_CATEGORIES})
        if not external:
            continue
        out.append(_finding(
            'CORR-001', 'HIGH', 'CORRECTNESS', process.node_id,
            f"{process.name}: calls {', '.join(external)} but defines no error "
            f'handler, so a failure outside the engine ends the process instance',
            'Add a catch for the fault types these activities raise, and decide '
            'explicitly whether the work is retried, compensated or dead-lettered.'))
    return out


def _corr_002_no_entry_point(analyzer) -> List[Dict[str, Any]]:
    """A process with no starter and no caller cannot run at all."""
    out = []
    for process in _by_label(analyzer, 'BWProcess'):
        if process.properties.get('entryType') not in (None, '', 'NONE'):
            continue
        if _incoming_types(analyzer, process.node_id).get('CALLS'):
            continue
        out.append(_finding(
            'CORR-002', 'MEDIUM', 'CORRECTNESS', process.node_id,
            f'{process.name}: has no starter and nothing in the analysed tree '
            f'calls it, so nothing in this estate can invoke it',
            'Confirm whether it is invoked from a module outside this analysis. '
            'If not, it is dead and should be removed rather than migrated.'))
    return out


# ── performance ───────────────────────────────────────────────────────
def _perf_001_select_star(analyzer) -> List[Dict[str, Any]]:
    out = []
    for activity in _by_label(analyzer, 'Activity'):
        statement = str(activity.properties.get('sqlStatement', '') or '')
        if not _SELECT_STAR_RE.search(statement):
            continue
        process = _process_of(analyzer, activity)
        where = f'{process.name}.' if process is not None else ''
        out.append(_finding(
            'PERF-001', 'MEDIUM', 'PERFORMANCE', activity.node_id,
            f'{where}{activity.name}: selects every column, so a column added '
            f'to the table changes the shape this activity maps from',
            'Name the columns the mapping actually uses. It documents the data '
            'contract and stops a schema change breaking the transformation.'))
    return out


# ── technical debt ────────────────────────────────────────────────────
def _debt_001_uncalled_process(analyzer) -> List[Dict[str, Any]]:
    """A sub-process nothing calls. Distinct from CORR-002: this one has a
    starter, so it runs -- it is just not part of any flow this tree shows."""
    out = []
    for process in _by_label(analyzer, 'BWProcess'):
        if process.properties.get('entryType') in (None, '', 'NONE'):
            continue
        incoming = _incoming_types(analyzer, process.node_id)
        if incoming.get('CALLS') or incoming.get('EXPOSES'):
            continue
        if process.properties.get('entryType') != 'NONE':
            continue
        out.append(_finding(
            'DEBT-001', 'LOW', 'TECH_DEBT', process.node_id,
            f'{process.name}: is neither called nor exposed within the analysed '
            f'tree', 'Confirm it is reachable from outside before migrating it.'))
    return out


def _debt_002_unused_shared_resource(analyzer) -> List[Dict[str, Any]]:
    out = []
    for resource in _by_label(analyzer, 'SharedResource'):
        incoming = _incoming_types(analyzer, resource.node_id)
        if incoming.get('REFERENCES') or incoming.get('CONFIGURED_BY'):
            continue
        out.append(_finding(
            'DEBT-002', 'LOW', 'TECH_DEBT', resource.node_id,
            f'{resource.name}: is defined but no process in the analysed tree '
            f'references it',
            'Remove it, or record why it is kept. An unused connection '
            'definition still has to be provisioned at deployment.'))
    return out


def _debt_003_unresolved_reference(analyzer) -> List[Dict[str, Any]]:
    out = []
    for node in _by_label(analyzer, 'ExternalReference'):
        out.append(_finding(
            'DEBT-003', 'MEDIUM', 'TECH_DEBT', node.node_id,
            f"{node.name}: is referenced but was not found in the scanned tree "
            f"({node.properties.get('targetPath', '')})",
            'Either the artefact lives in a module outside this analysis, or '
            'the reference is stale. Until it is resolved this dependency is '
            'missing from every blast radius.'))
    return out
