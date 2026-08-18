"""Computed inventories.

Every number a report or a context pack prints comes from here, so the same
question always has the same answer whichever surface asks it.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from analyzer_core.model import Graph, GraphNode

from .traverse import WRITE_RELS, ascend, descend, owning_page


def application_summary(graph: Graph) -> Dict[str, Any]:
    applications = graph.by_label('ApexApplication')
    application = applications[0] if applications else None
    stats = graph.stats()
    coverage = (graph.meta or {}).get('coverage', {})
    return {
        'applicationId': application.properties.get('applicationId') if application else None,
        'name': application.name if application else 'unknown',
        'alias': application.properties.get('alias', '') if application else '',
        'parsingSchema': application.properties.get('parsingSchema', '') if application else '',
        'apexVersion': application.properties.get('apexVersion', '') if application else '',
        'pages': len(graph.by_label('ApexPage')),
        'regions': len(graph.by_label('ApexRegion')),
        'items': len(graph.by_label('ApexItem')),
        'buttons': len(graph.by_label('ApexButton')),
        'processes': len(graph.by_label('ApexProcess')),
        'dynamicActions': len(graph.by_label('ApexDynamicAction')),
        'validations': len(graph.by_label('ApexValidation')),
        'branches': len(graph.by_label('ApexBranch')),
        'lovs': len(graph.by_label('ApexLov')),
        'authorizationSchemes': len(graph.by_label('ApexAuthorization')),
        'sqlStatements': len(graph.by_label('SqlStatement')),
        'plsqlBlocks': len(graph.by_label('PlsqlBlock')),
        'tables': len(graph.by_label('DbTable')),
        'views': len(graph.by_label('DbView')),
        'packages': len(graph.by_label('DbPackage')),
        'programUnits': len(graph.by_label('DbProgramUnit')),
        'columns': len(graph.by_label('DbColumn')),
        'issues': len(graph.by_label('Issue')),
        'totalNodes': stats['totalNodes'],
        'totalRelationships': stats['totalRelationships'],
        'authCoverage': application.properties.get('authCoverage', 0.0) if application else 0.0,
        'sqlReuseFactor': application.properties.get('sqlReuseFactor', 0.0)
                          if application else 0.0,
        'resolutionCoverage': coverage.get('resolutionCoverage', None),
        'dictionaryAvailable': coverage.get('dictionaryAvailable', False),
        'ingestionMode': (graph.meta or {}).get('ingestion', {}).get('mode', 'unknown'),
    }


def page_inventory(graph: Graph) -> List[Dict[str, Any]]:
    rows = []
    for page in graph.by_label('ApexPage'):
        properties = page.properties
        rows.append({
            'pageId': properties.get('pageId'),
            'name': page.name,
            'alias': properties.get('alias', ''),
            'group': properties.get('pageGroup', ''),
            'mode': properties.get('pageMode', ''),
            'tier': properties.get('tier', ''),
            'complexityScore': properties.get('complexityScore', 0),
            'regions': properties.get('regionCount', 0),
            'items': properties.get('itemCount', 0),
            'processes': properties.get('processCount', 0),
            'dynamicActions': properties.get('dynamicActionCount', 0),
            'sql': properties.get('sqlStatementCount', 0),
            'plsql': properties.get('plsqlBlockCount', 0),
            'tables': properties.get('tableCount', 0),
            'writes': properties.get('writeCount', 0),
            'unresolved': properties.get('unresolvedCount', 0),
            'authorization': properties.get('authorizationScheme', ''),
            'accessProtection': properties.get('pageAccessProtection', ''),
            'nodeId': page.node_id,
            'sourceFile': properties.get('sourceFile', ''),
        })
    rows.sort(key=lambda r: (-float(r['complexityScore'] or 0), r['pageId'] or 0))
    return rows


def complexity_ranking(graph: Graph, limit: int = 25) -> List[Dict[str, Any]]:
    return page_inventory(graph)[:limit]


def tier_distribution(graph: Graph) -> Dict[str, int]:
    counts = Counter(str(p.properties.get('tier', 'Unknown'))
                     for p in graph.by_label('ApexPage'))
    return {tier: counts.get(tier, 0)
            for tier in ('Critical', 'High', 'Medium', 'Low') if counts.get(tier)}


def security_posture(graph: Graph) -> Dict[str, Any]:
    pages = graph.by_label('ApexPage')
    unsecured, public, unprotected = [], [], []
    for page in pages:
        secured = any(r.rel_type == 'SECURED_BY' for r in graph.outgoing(page.node_id))
        if not secured:
            unsecured.append(_page_ref(page))
        if page.properties.get('isPublic'):
            public.append(_page_ref(page))
        if str(page.properties.get('pageAccessProtection', '')).upper() == 'UNRESTRICTED':
            unprotected.append(_page_ref(page))
    return {
        'pages': len(pages),
        'securedPages': len(pages) - len(unsecured),
        'unsecuredPages': unsecured,
        'publicPages': public,
        'unrestrictedAccessPages': unprotected,
        'authorizationSchemes': [
            {'name': scheme.name, 'type': scheme.properties.get('schemeType', ''),
             'usedBy': sum(1 for r in graph.incoming(scheme.node_id)
                           if r.rel_type == 'SECURED_BY')}
            for scheme in graph.by_label('ApexAuthorization')],
    }


def data_access(graph: Graph) -> List[Dict[str, Any]]:
    """Per table: which pages read it, which write it, how deep the coupling is."""
    rows = []
    for label in ('DbTable', 'DbView'):
        for table in graph.by_label(label):
            readers, writers = set(), set()
            for rel in graph.incoming(table.node_id):
                if rel.rel_type not in ({'READS_FROM', 'SOURCED_FROM'} | WRITE_RELS):
                    continue
                for page in ascend(graph, rel.start_id, max_depth=8):
                    node = graph.node(page)
                    if node is not None and node.label == 'ApexPage':
                        (writers if rel.rel_type in WRITE_RELS else readers).add(node.name)
            rows.append({
                'owner': table.properties.get('owner', ''),
                'name': table.name,
                'label': label,
                'numRows': table.properties.get('numRows', 0),
                'columns': sum(1 for r in graph.outgoing(table.node_id)
                               if r.rel_type == 'HAS_COLUMN'),
                'fanIn': table.properties.get('fanIn', 0),
                'readBy': sorted(readers),
                'writtenBy': sorted(writers),
            })
    rows.sort(key=lambda r: (-int(r['fanIn'] or 0), r['name']))
    return rows


def dead_code(graph: Graph) -> Dict[str, List[Dict[str, Any]]]:
    unreachable_pages = [
        _page_ref(page) for page in graph.by_label('ApexPage')
        if page.properties.get('pageId') not in (0, 1, 101)
        and not any(r.rel_type == 'NAVIGATES_TO' for r in graph.incoming(page.node_id))]

    unused_lovs = [{'name': lov.name, 'type': lov.properties.get('lovType', '')}
                   for lov in graph.by_label('ApexLov')
                   if not any(r.rel_type == 'USES_LOV'
                              for r in graph.incoming(lov.node_id))]

    unused_schemes = [{'name': scheme.name} for scheme in graph.by_label('ApexAuthorization')
                      if not any(r.rel_type == 'SECURED_BY'
                                 for r in graph.incoming(scheme.node_id))]

    unreached_units = []
    for unit in graph.by_label('DbProgramUnit'):
        reaching = ascend(graph, unit.node_id, max_depth=8)
        # any APEX component counts, not only a page: an authorization scheme
        # and an application-level process are real callers
        if not any(graph.node(n).label.startswith('Apex') for n in reaching
                   if graph.node(n) is not None):
            unreached_units.append({
                'owner': unit.properties.get('owner', ''),
                'package': unit.properties.get('packageName', ''),
                'name': unit.name,
            })

    unreached_tables = []
    for table in graph.by_label('DbTable'):
        if not any(r.rel_type in ({'READS_FROM', 'SOURCED_FROM'} | WRITE_RELS)
                   for r in graph.incoming(table.node_id)):
            unreached_tables.append({'owner': table.properties.get('owner', ''),
                                     'name': table.name})

    return {
        'unreachablePages': unreachable_pages,
        'unusedLovs': unused_lovs,
        'unusedAuthorizationSchemes': unused_schemes,
        'programUnitsNotReached': unreached_units,
        'tablesNoComponentTouches': unreached_tables,
    }


def hotspots(graph: Graph, limit: int = 25) -> List[Dict[str, Any]]:
    rows = []
    for label in ('DbTable', 'DbView', 'DbPackage', 'DbProgramUnit', 'ApexLov',
                  'SqlStatement', 'PlsqlBlock'):
        for node in graph.by_label(label):
            dependents = len(graph.incoming(node.node_id))
            if dependents < 2:
                continue
            rows.append({'label': label, 'name': node.name,
                         'dependents': dependents,
                         'pagesReaching': node.properties.get('fanIn', ''),
                         'nodeId': node.node_id})
    rows.sort(key=lambda r: -r['dependents'])
    return rows[:limit]


def issues_summary(graph: Graph) -> Dict[str, Any]:
    issues = graph.by_label('Issue')
    by_severity: Counter = Counter()
    by_category: Counter = Counter()
    by_rule: Counter = Counter()
    for issue in issues:
        by_severity[issue.properties.get('severity', 'UNKNOWN')] += 1
        by_category[issue.properties.get('category', 'UNKNOWN')] += 1
        by_rule[issue.properties.get('ruleId', '')] += 1

    order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'INFO': 4}
    rows = sorted(
        ({'ruleId': issue.properties.get('ruleId', ''),
          'severity': issue.properties.get('severity', ''),
          'category': issue.properties.get('category', ''),
          'title': issue.properties.get('title', ''),
          'description': issue.properties.get('description', ''),
          'pageId': issue.properties.get('pageId', ''),
          'sourceFile': issue.properties.get('sourceFile', ''),
          'evidence': issue.properties.get('evidence', '')}
         for issue in issues),
        key=lambda r: (order.get(r['severity'], 9), r['ruleId'], str(r['pageId'])))
    return {
        'total': len(issues),
        'bySeverity': dict(by_severity.most_common()),
        'byCategory': dict(by_category.most_common()),
        'byRule': dict(by_rule.most_common()),
        'findings': rows,
    }


def navigation(graph: Graph) -> List[Dict[str, Any]]:
    edges = []
    for rel in graph.rels:
        if rel.rel_type != 'NAVIGATES_TO':
            continue
        source = graph.node(rel.start_id)
        target = graph.node(rel.end_id)
        if source is None or target is None:
            continue
        page = owning_page(graph, source.node_id) or source
        edges.append({'fromPage': page.properties.get('pageId', ''),
                      'fromName': page.name,
                      'via': f'{source.label}:{source.name}',
                      'toPage': target.properties.get('pageId', ''),
                      'toName': target.name})
    edges.sort(key=lambda e: (str(e['fromPage']), str(e['toPage'])))
    return edges


def business_functions(graph: Graph) -> List[Dict[str, Any]]:
    rows = []
    for function in graph.by_label('BusinessFunction'):
        implemented = [graph.node(r.end_id).name for r in graph.outgoing(function.node_id)
                       if r.rel_type == 'IMPLEMENTED_BY' and graph.node(r.end_id)]
        rows.append({'name': function.name,
                     'domain': function.properties.get('domain', ''),
                     'criticality': function.properties.get('criticality', ''),
                     'origin': function.properties.get('origin', ''),
                     'confidence': function.properties.get('confidence', ''),
                     'implementedBy': implemented,
                     'description': function.properties.get('description', '')})
    rows.sort(key=lambda r: (r['domain'], r['name']))
    return rows


def full_inventory(graph: Graph) -> Dict[str, Any]:
    return {
        'summary': application_summary(graph),
        'tierDistribution': tier_distribution(graph),
        'pages': page_inventory(graph),
        'security': security_posture(graph),
        'dataAccess': data_access(graph),
        'deadCode': dead_code(graph),
        'hotspots': hotspots(graph),
        'issues': issues_summary(graph),
        'navigation': navigation(graph),
        'businessFunctions': business_functions(graph),
        'coverage': (graph.meta or {}).get('coverage', {}),
        'ingestion': (graph.meta or {}).get('ingestion', {}),
        'unhandledProcedures': (graph.meta or {}).get('unhandledProcedures', {}),
    }


def _page_ref(page: GraphNode) -> Dict[str, Any]:
    return {'pageId': page.properties.get('pageId'), 'name': page.name,
            'tier': page.properties.get('tier', ''),
            'nodeId': page.node_id}
