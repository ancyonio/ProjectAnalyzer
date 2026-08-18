"""Deterministic inventory, complexity, dead-code and risk analytics.

Everything in this module is derived arithmetic over the graph: no
model calls, no guessing. The LLM's job is to explain these numbers and
decide what to do about them, not to produce them.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Set

from ..constants import ENTRY_POINT_CATEGORIES, EXTERNAL_CALL_CATEGORIES
from ..model import Graph, GraphNode


# ──────────────────────────────────────────────────────────────
# Entry points
# ──────────────────────────────────────────────────────────────
def entry_points(graph: Graph) -> List[Dict[str, Any]]:
    """Every externally reachable process, with its Spring Boot target."""
    rows = []
    for proc in graph.by_label('BWProcess'):
        etype = proc.properties.get('entryType', 'NONE')
        if etype in (None, '', 'NONE'):
            continue
        starters = [graph.node(r.end_id) for r in graph.outgoing(proc.node_id)
                    if r.rel_type == 'EXECUTES']
        starter_names = [a.name for a in starters
                         if a and a.properties.get('category') in ENTRY_POINT_CATEGORIES]
        rows.append({
            'process': proc.name,
            'nodeId': proc.node_id,
            'module': proc.module,
            'entryType': etype,
            'springTarget': ENTRY_POINT_CATEGORIES.get(etype, 'Manual review'),
            'endpoint': proc.properties.get('endpoint', ''),
            'starterActivities': starter_names,
            'complexityScore': proc.properties.get('complexityScore', 0),
            'tier': proc.properties.get('tier', ''),
            'filePath': proc.file_path,
        })
    return sorted(rows, key=lambda r: (r['entryType'], -float(r['complexityScore'] or 0)))


# ──────────────────────────────────────────────────────────────
# Complexity
# ──────────────────────────────────────────────────────────────
def complexity_ranking(graph: Graph) -> List[Dict[str, Any]]:
    """Processes ranked by complexity, enriched with graph-derived counts."""
    rows = []
    for proc in graph.by_label('BWProcess'):
        out = graph.outgoing(proc.node_id)
        counts: Counter = Counter(r.rel_type for r in out)
        callers = [r for r in graph.incoming(proc.node_id) if r.rel_type == 'CALLS']
        rows.append({
            'process': proc.name,
            'nodeId': proc.node_id,
            'module': proc.module,
            'tier': proc.properties.get('tier', ''),
            'score': float(proc.properties.get('complexityScore', 0) or 0),
            'activities': int(proc.properties.get('activityCount', 0) or 0),
            'transitions': int(proc.properties.get('transitionCount', 0) or 0),
            'errorHandlers': int(proc.properties.get('errorHandlerCount', 0) or 0),
            'groups': int(proc.properties.get('groupCount', 0) or 0),
            'schemas': counts.get('USES_XSD', 0),
            'sharedResources': counts.get('REFERENCES', 0),
            'calledBy': len(callers),
            'entryType': proc.properties.get('entryType', 'NONE'),
            'filePath': proc.file_path,
        })
    return sorted(rows, key=lambda r: -r['score'])


def tier_distribution(graph: Graph) -> Dict[str, int]:
    dist: Counter = Counter()
    for proc in graph.by_label('BWProcess'):
        dist[proc.properties.get('tier', 'Unknown')] += 1
    order = ['Critical', 'High', 'Medium', 'Low', 'Unknown']
    return {t: dist.get(t, 0) for t in order if dist.get(t, 0)}


# ──────────────────────────────────────────────────────────────
# Dead code
# ──────────────────────────────────────────────────────────────
def dead_code(graph: Graph) -> Dict[str, List[Dict[str, str]]]:
    """Artefacts nothing references. Candidates to drop from migration scope."""
    orphan_schemas = []
    for xsd in graph.by_label('XSD'):
        used = [r for r in graph.incoming(xsd.node_id)
                if r.rel_type in ('USES_XSD', 'IMPORTS_SCHEMA')]
        if not used:
            orphan_schemas.append({'name': xsd.name, 'location': xsd.file_path,
                                   'namespace': xsd.properties.get('namespace', '')})

    unreachable = []
    for proc in graph.by_label('BWProcess'):
        called = [r for r in graph.incoming(proc.node_id) if r.rel_type == 'CALLS']
        etype = proc.properties.get('entryType', 'NONE')
        if not called and etype in (None, '', 'NONE'):
            unreachable.append({'name': proc.name, 'module': proc.module,
                                'location': proc.file_path})

    unused_resources = []
    for res in graph.by_label('SharedResource'):
        used = [r for r in graph.incoming(res.node_id) if r.rel_type == 'REFERENCES']
        if not used:
            unused_resources.append({'name': res.name,
                                     'type': str(res.properties.get('resourceType', '')),
                                     'location': res.file_path})

    unused_services = []
    for svc in graph.by_label('Service'):
        used = [r for r in graph.incoming(svc.node_id)
                if r.rel_type in ('USES_WSDL', 'CALLS', 'EXPOSES')]
        if not used:
            unused_services.append({'name': svc.name, 'location': svc.file_path,
                                    'namespace': str(svc.properties.get('namespace', ''))})

    unused_transforms = []
    for tr in graph.by_label('DataTransformation'):
        if not graph.incoming(tr.node_id):
            unused_transforms.append({'name': tr.name, 'location': tr.file_path})

    return {
        'orphanSchemas': orphan_schemas,
        'unreachableProcesses': unreachable,
        'unusedSharedResources': unused_resources,
        'unusedServices': unused_services,
        'unreferencedTransformations': unused_transforms,
    }


# ──────────────────────────────────────────────────────────────
# Cycles
# ──────────────────────────────────────────────────────────────
def process_call_edges(graph: Graph) -> List[tuple]:
    """Process → process call edges, collapsing the intermediate Activity."""
    edges = []
    for act in graph.by_label('Activity'):
        proc_id = act.properties.get('processRef')
        if not proc_id:
            continue
        for rel in graph.outgoing(act.node_id):
            if rel.rel_type == 'CALLS':
                edges.append((proc_id, rel.end_id, act.name))
    return edges


def circular_dependencies(graph: Graph) -> List[List[str]]:
    """Cycles in the process call graph (migration blockers)."""
    adj: Dict[str, Set[str]] = defaultdict(set)
    for src, dst, _ in process_call_edges(graph):
        adj[src].add(dst)

    cycles: List[List[str]] = []
    seen_cycles: Set[tuple] = set()
    state: Dict[str, int] = {}
    stack: List[str] = []

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for nxt in sorted(adj.get(node, ())):
            if state.get(nxt, 0) == 0:
                visit(nxt)
            elif state.get(nxt) == 1:
                idx = stack.index(nxt)
                cycle = stack[idx:] + [nxt]
                names = tuple(graph.nodes[n].name if n in graph.nodes else n for n in cycle)
                key = tuple(sorted(set(names)))
                if key not in seen_cycles:
                    seen_cycles.add(key)
                    cycles.append(list(names))
        stack.pop()
        state[node] = 2

    for node in sorted(adj):
        if state.get(node, 0) == 0:
            visit(node)
    return cycles


# ──────────────────────────────────────────────────────────────
# Hotspots, modules, integrations
# ──────────────────────────────────────────────────────────────
def hotspots(graph: Graph, limit: int = 25) -> List[Dict[str, Any]]:
    """Most-depended-upon artefacts: highest blast radius per unit of change."""
    rows = []
    for node in graph.nodes.values():
        if node.label not in ('XSD', 'BWProcess', 'SharedResource', 'GlobalVariable',
                              'Service', 'Element'):
            continue
        dependents = [r for r in graph.incoming(node.node_id)
                      if r.rel_type not in ('BELONGS_TO', 'EXECUTES', 'CONTAINS')]
        if not dependents:
            continue
        rows.append({
            'type': node.label,
            'name': node.name,
            'nodeId': node.node_id,
            'module': node.module,
            'dependents': len(dependents),
            'relationTypes': sorted({r.rel_type for r in dependents}),
            'filePath': node.file_path,
        })
    return sorted(rows, key=lambda r: -r['dependents'])[:limit]


def module_metrics(graph: Graph) -> List[Dict[str, Any]]:
    rows = []
    for mod in sorted(graph.modules()):
        members = [n for n in graph.nodes.values() if n.module == mod]
        counts = Counter(n.label for n in members)
        procs = [n for n in members if n.label == 'BWProcess']
        rows.append({
            'module': mod,
            'processes': counts.get('BWProcess', 0),
            'activities': counts.get('Activity', 0),
            'schemas': counts.get('XSD', 0),
            'services': counts.get('Service', 0),
            'globalVariables': counts.get('GlobalVariable', 0),
            'sharedResources': counts.get('SharedResource', 0),
            'transformations': counts.get('DataTransformation', 0),
            'entryPoints': sum(1 for p in procs
                               if p.properties.get('entryType') not in (None, '', 'NONE')),
            'totalComplexity': round(sum(float(p.properties.get('complexityScore', 0) or 0)
                                         for p in procs), 1),
        })
    return sorted(rows, key=lambda r: -r['totalComplexity'])


def module_dependencies(graph: Graph) -> List[Dict[str, Any]]:
    deps: Counter = Counter()
    for src, dst, _ in process_call_edges(graph):
        src_mod = graph.nodes[src].module if src in graph.nodes else ''
        dst_mod = graph.nodes[dst].module if dst in graph.nodes else ''
        if src_mod and dst_mod and src_mod != dst_mod:
            deps[(src_mod, dst_mod)] += 1
    return [{'from': a, 'to': b, 'calls': c}
            for (a, b), c in sorted(deps.items(), key=lambda kv: -kv[1])]


def integration_surface(graph: Graph) -> List[Dict[str, Any]]:
    """Outbound integrations: every activity that leaves the process boundary."""
    rows: Dict[str, Dict[str, Any]] = {}
    for act in graph.by_label('Activity'):
        category = str(act.properties.get('category', ''))
        if category not in EXTERNAL_CALL_CATEGORIES:
            continue
        proc = graph.node(str(act.properties.get('processRef', '')))
        key = f"{category}|{act.properties.get('springEquivalent', '')}"
        row = rows.setdefault(key, {
            'category': category,
            'springTarget': act.properties.get('springEquivalent', ''),
            'count': 0,
            'processes': set(),
        })
        row['count'] += 1
        if proc:
            row['processes'].add(proc.name)
    out = []
    for row in rows.values():
        row['processes'] = sorted(row['processes'])
        out.append(row)
    return sorted(out, key=lambda r: -r['count'])


def error_handling_gaps(graph: Graph, min_activities: int = 3) -> List[Dict[str, Any]]:
    rows = []
    for proc in graph.by_label('BWProcess'):
        has_handler = any(r.rel_type == 'HANDLES_ERROR' for r in graph.outgoing(proc.node_id))
        activities = int(proc.properties.get('activityCount', 0) or 0)
        if not has_handler and activities >= min_activities:
            rows.append({'process': proc.name, 'module': proc.module,
                         'activities': activities,
                         'tier': proc.properties.get('tier', ''),
                         'entryType': proc.properties.get('entryType', 'NONE')})
    return sorted(rows, key=lambda r: -r['activities'])


def migration_sequence(graph: Graph) -> List[Dict[str, Any]]:
    """Dependency-ordered migration waves.

    Wave 1 = leaf processes (call nothing). Each later wave may only depend on
    processes already migrated in earlier waves. Cyclic remainders are flagged.
    """
    procs = {p.node_id: p for p in graph.by_label('BWProcess')}
    deps: Dict[str, Set[str]] = {pid: set() for pid in procs}
    for src, dst, _ in process_call_edges(graph):
        if src in deps and dst in procs and src != dst:
            deps[src].add(dst)

    waves: List[Dict[str, Any]] = []
    migrated: Set[str] = set()
    remaining = dict(deps)
    wave_no = 1
    while remaining:
        ready = [pid for pid, d in remaining.items() if not (d - migrated)]
        if not ready:  # cycle: take the least-coupled node to break the deadlock
            ready = [min(remaining, key=lambda p: len(remaining[p] - migrated))]
            note = 'cycle broken manually - review circular dependencies'
        else:
            note = ''
        ready.sort(key=lambda p: float(procs[p].properties.get('complexityScore', 0) or 0))
        waves.append({
            'wave': wave_no,
            'note': note,
            'processes': [{
                'process': procs[p].name,
                'module': procs[p].module,
                'tier': procs[p].properties.get('tier', ''),
                'score': float(procs[p].properties.get('complexityScore', 0) or 0),
                'entryType': procs[p].properties.get('entryType', 'NONE'),
            } for p in ready],
        })
        migrated.update(ready)
        for pid in ready:
            remaining.pop(pid, None)
        wave_no += 1
        if wave_no > 100:  # safety valve
            break
    return waves


def full_inventory(graph: Graph) -> Dict[str, Any]:
    """One structured object holding every deterministic finding."""
    dc = dead_code(graph)
    return {
        'stats': graph.stats(),
        'meta': graph.meta,
        'entryPoints': entry_points(graph),
        'complexity': {
            'tierDistribution': tier_distribution(graph),
            'ranking': complexity_ranking(graph),
        },
        'deadCode': dc,
        'deadCodeTotals': {k: len(v) for k, v in dc.items()},
        'circularDependencies': circular_dependencies(graph),
        'hotspots': hotspots(graph),
        'modules': module_metrics(graph),
        'moduleDependencies': module_dependencies(graph),
        'integrationSurface': integration_surface(graph),
        'errorHandlingGaps': error_handling_gaps(graph),
        'migrationSequence': migration_sequence(graph),
    }
