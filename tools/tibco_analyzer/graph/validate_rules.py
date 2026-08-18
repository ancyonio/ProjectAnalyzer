"""TIBCO-specific validation rules.

The generic checks — id grammar, referential integrity, closed vocabulary,
property typing, orphans, provenance — live in `analyzer_core.graph.validate`.
These are the ones that depend on what the TIBCO vocabulary *means*, and they
are supplied to the engine through `ValidationConfig.extra_rules`.

Two of them exist because of defects this analyzer actually shipped.
`shared-resource-coverage` catches a parser that discovered resource files and
modelled none: the integration surface is then empty, which is
indistinguishable in a node count from an estate with no external systems, and
leads to the opposite conclusion. `artifact-coverage` catches a partly-parsed
tree being read as a small estate.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Callable, List, Optional

from analyzer_core.graph.validate import Finding
from analyzer_core.model import Graph

from ..constants import EXPECTED_REL_TYPES

# Extensions that hold a shared resource in either BW generation. Used to tell
# "this estate has no shared resources" apart from "the parser did not
# recognise this estate's shared resources", which are very different
# statements to put in front of an analyst.
_RESOURCE_EXT_HINTS = ('.shared', '.rvtransport', '.httpproxy', '.id')


def node_name_present(graph: Graph) -> List[Finding]:
    unnamed = [node.node_id for node in graph.nodes.values() if not node.name]
    if unnamed:
        return [Finding('WARNING', 'node-name-present',
                        f'{len(unnamed)} nodes have an empty name', unnamed)]
    return []


def no_self_loops(graph: Graph) -> List[Finding]:
    loops = [f'{r.start_id}-[{r.rel_type}]->{r.end_id}'
             for r in graph.rels if r.start_id == r.end_id]
    if loops:
        return [Finding('WARNING', 'no-self-loops',
                        f'{len(loops)} self-referencing relationships', loops)]
    return []


def relationship_coverage(graph: Graph) -> List[Finding]:
    """Expected edge types that are absent.

    A warning, not an error: it can mean the estate is simple, or that the
    parser does not model them yet. `artifact-coverage` is what tells those
    two apart, which is why this finding points at it.
    """
    missing = EXPECTED_REL_TYPES - {r.rel_type for r in graph.rels}
    if missing:
        return [Finding('WARNING', 'relationship-coverage',
                        'Expected relationship types absent - either the source '
                        'tree does not use them or the parser does not yet model '
                        'them; check artifact-coverage before concluding the '
                        'estate is simple', sorted(missing))]
    return []


def shared_resource_coverage(graph: Graph) -> List[Finding]:
    """Resource files on disk but no SharedResource nodes means a parser gap."""
    discovery = (graph.meta or {}).get('fileDiscovery') or {}
    if not discovery:
        return []
    resource_files = {
        ext: count for ext, count in discovery.items()
        if ext and (ext.lower().endswith('resource')
                    or ext.lower().startswith(_RESOURCE_EXT_HINTS)
                    or ext.lower().endswith('globalinstance'))
    }
    total = sum(resource_files.values())
    parsed = len(graph.by_label('SharedResource'))
    if total and not parsed:
        return [Finding('ERROR', 'shared-resource-coverage',
                        f'{total} shared-resource files were discovered but none '
                        f'were parsed - the integration surface in this graph is '
                        f'empty and must not be reported as "no external systems"',
                        [f'{ext}: {n}' for ext, n in sorted(resource_files.items())])]
    if total:
        return [Finding('INFO', 'shared-resource-coverage',
                        f'{parsed} shared resource(s) parsed from {total} '
                        f'resource file(s)')]
    return []


def artifact_coverage(graph: Graph) -> List[Finding]:
    """How much of the supported TIBCO input is represented in the graph.

    An analyst reading a context pack cannot otherwise tell whether a small
    graph means a small estate or a partly-parsed one.
    """
    meta = graph.meta or {}
    discovery = meta.get('fileDiscovery') or {}
    discovered = sum(discovery.values())
    if not discovered:
        return []
    coverage = meta.get('coverage') or {}
    modelled = coverage.get('filesModelled', 0)
    supported = coverage.get('filesSupported')
    supported_modelled = coverage.get('filesSupportedModelled')
    if supported is None or supported_modelled is None:
        supported, supported_modelled = discovered, modelled
    pct = coverage.get('artifactCoverage')
    if pct is None:
        pct = round(supported_modelled * 100.0 / supported, 1) if supported else 0.0
    estate_pct = coverage.get('estateFileCoverage')
    if estate_pct is None:
        estate_pct = round(modelled * 100.0 / discovered, 1)
    classified = sum((meta.get('artifactFamilies') or {}).values())
    detail = [f'{supported_modelled}/{supported} supported artifact files produced graph nodes',
              f'{modelled}/{discovered} all discovered files produced graph nodes ({estate_pct}%)',
              f'{classified}/{discovered} files matched a known artifact family']
    if pct < 50:
        return [Finding('WARNING', 'artifact-coverage',
                        f'Only {pct}% of supported artifact files are represented '
                        f'in the graph - the parser may be missing TIBCO inputs',
                        detail)]
    return [Finding('INFO', 'artifact-coverage',
                    f'{pct}% of supported artifact files are represented in the '
                    f'graph; all-file estate coverage is {estate_pct}%', detail)]


def process_completeness(graph: Graph) -> List[Finding]:
    no_module, no_work = [], []
    for process in graph.by_label('BWProcess'):
        out_types = {r.rel_type for r in graph.outgoing(process.node_id)}
        if 'BELONGS_TO' not in out_types:
            no_module.append(process.name)
        if not ({'EXECUTES', 'USES_XSD', 'USES_WSDL', 'HAS_GROUP'} & out_types):
            no_work.append(process.name)
    findings = []
    if no_module:
        findings.append(Finding('ERROR', 'process-module-membership',
                                f'{len(no_module)} BWProcess nodes have no '
                                f'BELONGS_TO edge', no_module))
    if no_work:
        findings.append(Finding('WARNING', 'process-has-work',
                                f'{len(no_work)} BWProcess nodes execute no '
                                f'activity and use no schema', no_work))
    return findings


def schema_wiring(graph: Graph) -> List[Finding]:
    empty = [x.name for x in graph.by_label('XSD')
             if not any(r.rel_type == 'CONTAINS' for r in graph.outgoing(x.node_id))]
    if empty:
        return [Finding('WARNING', 'xsd-contains-elements',
                        f'{len(empty)} XSD nodes define no elements or types', empty)]
    return []


def entry_points_detected(graph: Graph) -> List[Finding]:
    entries = [p for p in graph.by_label('BWProcess')
               if p.properties.get('entryType') not in (None, '', 'NONE')]
    if not entries:
        return [Finding('WARNING', 'entry-points-detected',
                        'No entry point processes detected - the analysis may be '
                        'missing starters')]
    return [Finding('INFO', 'entry-points-detected',
                    f'{len(entries)} entry point processes detected')]


def unresolved_references(graph: Graph) -> List[Finding]:
    external = graph.by_label('ExternalReference')
    if external:
        return [Finding('WARNING', 'unresolved-references',
                        f'{len(external)} referenced artefacts were not found in '
                        f'the scanned tree',
                        [f"{n.name} ({n.properties.get('targetPath', '')})"
                         for n in external])]
    return []


def csv_roundtrip(output_dir: Optional[Path]) -> Callable[[Graph], List[Finding]]:
    """Check the exported CSV pair, when one has been written.

    A closure rather than a plain rule, because the engine hands rules a graph
    and nothing else, and this one needs the output directory.
    """
    def _rule(graph: Graph) -> List[Finding]:
        if output_dir is None:
            return []
        nodes_csv = Path(output_dir) / 'neo4j_nodes.csv'
        rels_csv = Path(output_dir) / 'neo4j_relationships.csv'
        if not nodes_csv.exists() or not rels_csv.exists():
            return [Finding('INFO', 'csv-present',
                            'CSV exports not found - skipping CSV checks')]
        with open(nodes_csv, newline='', encoding='utf-8') as handle:
            node_ids = {row['nodeId:ID'] for row in csv.DictReader(handle)}
        bad = []
        with open(rels_csv, newline='', encoding='utf-8') as handle:
            for row in csv.DictReader(handle):
                if row[':START_ID'] not in node_ids or row[':END_ID'] not in node_ids:
                    bad.append(f"{row[':START_ID']}->{row[':END_ID']}")
        if bad:
            return [Finding('ERROR', 'csv-referential-integrity',
                            f'{len(bad)} CSV relationships point at unknown node '
                            f'ids', bad)]
        return [Finding('INFO', 'csv-referential-integrity',
                        f'CSV integrity verified across {len(node_ids)} node ids')]

    _rule.__name__ = 'csv_roundtrip'
    return _rule


TIBCO_RULES = [
    node_name_present,
    no_self_loops,
    relationship_coverage,
    shared_resource_coverage,
    artifact_coverage,
    process_completeness,
    schema_wiring,
    entry_points_detected,
    unresolved_references,
]
