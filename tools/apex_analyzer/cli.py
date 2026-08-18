"""Command line interface.

    apex-analyze analyze   --source <export_root> [--app-id 100] [--db-meta db_meta.json]
    apex-analyze validate  [--strict]
    apex-analyze impact    --target "DbProgramUnit:CREATE_ORDER" [--depth 8]
    apex-analyze rules     [--category SECURITY] [--min-severity HIGH]
    apex-analyze diagrams  [--format mermaid|plantuml|both]
    apex-analyze context   (LLM grounding packs)
    apex-analyze report    (Step00/01/02 scaffolds)
    apex-analyze queries   (Cypher cookbook)
    apex-analyze diff      --baseline <other graph.json>
    apex-analyze all       --source <export_root>

Every command except `analyze` reads `<output>/graph.json`, so the expensive
parse happens once. Exit codes: 0 ok, 1 usage/runtime error, 2 gate failure
(use in CI).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from analyzer_core.analysis.impact import ImpactAnalyzer
from analyzer_core.analysis.impact import render_markdown as impact_markdown
from analyzer_core.analysis.impact import render_mermaid as impact_mermaid
from analyzer_core.cli_base import load_graph, print_stats, setup_logging, write
from analyzer_core.graph.exporters import Neo4jExporter
from analyzer_core.graph.validate import GraphValidator
from analyzer_core.graph.validate import render_markdown as validation_markdown
from analyzer_core.model import Graph

from .analysis.inventory import full_inventory
from .analyzer import ApexAnalyzer
from .graph.queries import render_cookbook, render_markdown as queries_markdown
from .graph.schema import impact_config, neo4j_schema, validation_config

DEFAULT_OUTPUT = 'analysis_output_apex'
GRAPH_FILE = 'graph.json'
SEVERITY_ORDER = ['INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

logger = None


# ──────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────

def _print_next(cli: str, args) -> None:
    """Say what `analyze` wrote, and what it did not.

    `analyze` produces the graph and the Neo4j export. The context packs, diagrams
    and report scaffolds come from separate commands, and leaving that implicit is
    how an output directory ends up looking complete while three of its folders were
    never created.
    """
    if getattr(args, 'running_all', False):
        return
    source = getattr(args, 'source', None)
    rerun = f'{cli} -o {args.output} all --source {source}' if source \
        else f'{cli} -o {args.output} all --source <root>'
    print(f'\n  Next: {cli} -o {args.output} validate')
    print('\n  `analyze` writes the graph and the Neo4j export only. It does not')
    print('  write context/, generated_diagrams/ or reports/. For the complete set:')
    print(f'\n    {rerun}')
    print(f'\n  or run the parts you need: {cli} context | diagrams | report\n')


def cmd_analyze(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    analyzer = ApexAnalyzer(
        args.source, output_dir,
        application_id=args.app_id,
        parsing_schema=args.schema or '',
        db_meta=args.db_meta,
        apex_meta=args.apex_meta,
        git_range=args.git_range or '',
        git_enabled=args.git,
    )
    graph = analyzer.analyze()
    graph.save(output_dir / GRAPH_FILE)

    files = Neo4jExporter(graph, output_dir, neo4j_schema()).write_all()
    write(output_dir / 'analysis_queries.cypher', render_cookbook(), logger)
    write(output_dir / 'ANALYSIS_QUERIES.md', queries_markdown(), logger)
    write(output_dir / 'analysis_summary.json',
          json.dumps(_summary(graph), indent=2, default=str), logger)

    print_stats(graph, 'APEX KNOWLEDGE GRAPH BUILT', output_dir, files)
    coverage = (graph.meta or {}).get('coverage', {})
    print('\n  COVERAGE:')
    print(f"   ingestion mode           : {(graph.meta or {}).get('ingestion', {}).get('mode')}")
    print(f"   dictionary available     : {coverage.get('dictionaryAvailable')}")
    if coverage.get('totalResolutions'):
        print(f"   resolution coverage      : {coverage['resolutionCoverage']:.0%} "
              f"({coverage['strongResolutions']}/{coverage['totalResolutions']})")
    if coverage.get('unresolvedNames'):
        print(f"   unresolved objects       : "
              f"{', '.join(coverage['unresolvedNames'][:8])}")
    unhandled = (graph.meta or {}).get('unhandledProcedures', {})
    if unhandled:
        print(f"   unhandled export calls   : {sum(unhandled.values())} "
              f"across {len(unhandled)} procedure(s)")
    _print_next('apex-analyze', args)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    graph = load_graph(output_dir, 'apex-analyze analyze --source <export_root>')
    result = GraphValidator(graph, validation_config(), output_dir).run()
    write(output_dir / 'validation_report.md',
          validation_markdown(result, 'APEX Graph Validation Report'), logger)
    write(output_dir / 'validation_report.json', json.dumps(result, indent=2), logger)

    print(f"\nValidation: {result['status']}  "
          f"(errors={result['errors']}, warnings={result['warnings']})")
    for finding in result['findings']:
        if finding['severity'] != 'INFO':
            print(f"  [{finding['severity']}] {finding['rule']}: {finding['message']}")
    if result['status'] == 'FAIL':
        return 2
    if args.strict and result['status'] == 'WARN':
        return 2
    return 0


def cmd_impact(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    graph = load_graph(output_dir)

    targets = []
    for ref in args.target:
        matches = graph.resolve(ref, label=args.label[0] if args.label else None)
        if not matches:
            print(f"ERROR: no component matches '{ref}'.", file=sys.stderr)
            return 1
        if len(matches) > 1 and not args.all_matches:
            print(f"Ambiguous target '{ref}' — {len(matches)} matches:", file=sys.stderr)
            for match in matches[:15]:
                print(f"  {match.label}:{match.name}  (id {match.node_id})", file=sys.stderr)
            print('Refine with --label, use the node id, or pass --all-matches.',
                  file=sys.stderr)
            return 1
        targets.extend(matches if args.all_matches else matches[:1])

    result = ImpactAnalyzer(graph, impact_config()).analyze(
        targets, depth=args.depth, direction=args.direction,
        include_rels=set(args.include_rel) if args.include_rel else None,
        exclude_rels=set(args.exclude_rel) if args.exclude_rel else None)

    print(json.dumps(result, indent=2) if args.json else impact_markdown(result))
    if args.save:
        base = Path(args.save)
        write(base.with_suffix('.md'), impact_markdown(result), logger)
        write(base.with_suffix('.json'), json.dumps(result, indent=2), logger)
        write(base.with_suffix('.mmd'), impact_mermaid(result), logger)
    if args.fail_on in ('CRITICAL', 'HIGH', 'MEDIUM'):
        order = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
        if order.index(result['summary']['riskBand']) >= order.index(args.fail_on):
            return 2
    return 0


def cmd_rules(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    graph = load_graph(output_dir)
    from .analysis.inventory import issues_summary
    summary = issues_summary(graph)

    minimum = SEVERITY_ORDER.index(args.min_severity) if args.min_severity else 0
    findings = [f for f in summary['findings']
                if SEVERITY_ORDER.index(f['severity']) >= minimum
                and (not args.category or f['category'] == args.category)
                and (not args.rule or f['ruleId'] == args.rule)]

    # `bySeverity` has to describe the findings actually shown. Reporting the
    # unfiltered breakdown next to a filtered count made the two contradict
    # each other whenever --min-severity/--category/--rule was in play.
    shown_by_severity = {sev: sum(1 for f in findings if f['severity'] == sev)
                         for sev in SEVERITY_ORDER}
    shown_by_severity = {sev: n for sev, n in shown_by_severity.items() if n}
    suppressed = len(summary['findings']) - len(findings)

    if args.json:
        print(json.dumps({'total': len(findings),
                          'bySeverity': shown_by_severity,
                          'totalBeforeFilter': len(summary['findings']),
                          'suppressedByFilter': suppressed,
                          'findings': findings}, indent=2))
    else:
        print(f"\n{len(findings)} finding(s)\n")
        for finding in findings:
            page = f" page {finding['pageId']}" if finding['pageId'] not in ('', None) \
                else ''
            print(f"  [{finding['severity']:<8}] {finding['ruleId']}{page}: "
                  f"{finding['description']}")
        print('\nBy severity:', shown_by_severity)
        if suppressed:
            print(f'({suppressed} further finding(s) hidden by the active '
                  f"filter; {len(summary['findings'])} in the graph)")
    if args.fail_on:
        threshold = SEVERITY_ORDER.index(args.fail_on)
        if any(SEVERITY_ORDER.index(f['severity']) >= threshold for f in findings):
            return 2
    return 0


def cmd_diagrams(args: argparse.Namespace) -> int:
    from .diagrams import mermaid, plantuml
    output_dir = Path(args.output)
    graph = load_graph(output_dir)
    target_dir = Path(args.diagram_dir) if args.diagram_dir \
        else output_dir / 'generated_diagrams'

    produced: Dict[str, str] = {}
    if args.format in ('mermaid', 'both'):
        produced.update(mermaid.generate_all(graph))
    if args.format in ('plantuml', 'both'):
        produced.update(plantuml.generate_all(graph))
    for name, content in produced.items():
        write(target_dir / name, content, logger)
    print(f'\n{len(produced)} diagram sources written to {target_dir}')
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    from .report.contextpack import ContextPackBuilder
    output_dir = Path(args.output)
    graph = load_graph(output_dir)
    written = ContextPackBuilder(graph, output_dir / 'context').build_all()
    print(f"\n{len(written)} context packs written to {output_dir / 'context'}")
    for name in sorted(written):
        print(f'  {name}')
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .report.reports import generate_reports
    output_dir = Path(args.output)
    graph = load_graph(output_dir)
    reports_dir = Path(args.reports_dir) if args.reports_dir else output_dir / 'reports'
    inventory = full_inventory(graph)
    written = generate_reports(graph, reports_dir, inventory)
    write(reports_dir / 'inventory.json', json.dumps(inventory, indent=2, default=str),
          logger)
    print(f'\nReports scaffolded in {reports_dir}:')
    for name in written:
        print(f'  {name}')
    print("\nSections marked `<!-- LLM: ... -->` are for the agent to complete.")
    return 0


def cmd_queries(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    write(output_dir / 'analysis_queries.cypher', render_cookbook(), logger)
    write(output_dir / 'ANALYSIS_QUERIES.md', queries_markdown(), logger)
    print(queries_markdown() if args.print_queries else f'Cookbook written to {output_dir}')
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    """Release comparison: two graphs, compared by natural key."""
    output_dir = Path(args.output)
    current = load_graph(output_dir)
    baseline = Graph.load(Path(args.baseline))

    current_ids = set(current.nodes)
    baseline_ids = set(baseline.nodes)
    added = sorted(current_ids - baseline_ids)
    removed = sorted(baseline_ids - current_ids)
    changed = []
    for node_id in sorted(current_ids & baseline_ids):
        a, b = current.nodes[node_id], baseline.nodes[node_id]
        keys = ('text', 'complexityScore', 'sourceType', 'processType', 'queryTable',
                'authorizationScheme', 'pageAccessProtection', 'sqlHash', 'codeHash')
        if any(a.properties.get(k) != b.properties.get(k) for k in keys):
            changed.append(node_id)

    result = {
        'baseline': str(args.baseline),
        'current': str(output_dir / GRAPH_FILE),
        'added': [_describe(current, n) for n in added],
        'removed': [_describe(baseline, n) for n in removed],
        'changed': [_describe(current, n) for n in changed],
        'counts': {'added': len(added), 'removed': len(removed), 'changed': len(changed)},
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"\nAdded   : {len(added)}\nRemoved : {len(removed)}\n"
              f"Changed : {len(changed)}\n")
        for kind in ('added', 'removed', 'changed'):
            for row in result[kind][:40]:
                print(f"  {kind:<8} {row['label']:<18} {row['name']}")
    if args.save:
        write(Path(args.save), json.dumps(result, indent=2), logger)
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    args.running_all = True
    rc = cmd_analyze(args)
    if rc:
        return rc
    validate_rc = cmd_validate(args)
    args.format = getattr(args, 'format', 'both')
    args.diagram_dir = getattr(args, 'diagram_dir', None)
    cmd_diagrams(args)
    cmd_context(args)
    args.reports_dir = getattr(args, 'reports_dir', None)
    cmd_report(args)
    args.category = getattr(args, 'category', None)
    args.rule = getattr(args, 'rule', None)
    args.min_severity = getattr(args, 'min_severity', 'MEDIUM')
    args.json = False
    args.fail_on = None
    cmd_rules(args)
    print('\nPipeline complete. Load the graph with '
          '`python scripts/push_to_neo4j.py -o ' + str(args.output) + '`.')
    return validate_rc


# ──────────────────────────────────────────────────────────────
def _summary(graph: Graph) -> Dict[str, Any]:
    inventory = full_inventory(graph)
    return {
        'summary': inventory['summary'],
        'tierDistribution': inventory['tierDistribution'],
        'issues': {'total': inventory['issues']['total'],
                   'bySeverity': inventory['issues']['bySeverity'],
                   'byRule': inventory['issues']['byRule']},
        'coverage': inventory['coverage'],
        'ingestion': inventory['ingestion'],
        'nodeCounts': graph.stats()['nodeCounts'],
        'relationshipCounts': graph.stats()['relationshipCounts'],
    }


def _describe(graph: Graph, node_id: str) -> Dict[str, str]:
    node = graph.nodes.get(node_id)
    return {'nodeId': node_id,
            'label': node.label if node else '',
            'name': node.name if node else '',
            'pageId': str(node.properties.get('pageId', '')) if node else ''}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='apex-analyze',
        description='Deterministic Oracle APEX analysis: knowledge graph, blast '
                    'radius, rule findings, diagrams and LLM context packs.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    parser.add_argument('--output', '-o', default=DEFAULT_OUTPUT,
                        help=f'Analysis output directory (default: {DEFAULT_OUTPUT})')
    parser.add_argument('--verbose', '-v', action='store_true')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('analyze', help='Parse an APEX export into a knowledge graph')
    _analyze_arguments(p)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser('validate', help='Validate graph integrity (CI gate)')
    p.add_argument('--strict', action='store_true', help='Treat warnings as failures')
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser('impact', help='Blast radius of changing a component')
    p.add_argument('--target', '-t', action='append', required=True,
                   help='Node id, name, or `Label:Name` (repeatable)')
    p.add_argument('--label', '-l', action='append', help='Disambiguate by label')
    p.add_argument('--depth', '-d', type=int, default=8)
    p.add_argument('--direction', default='upstream',
                   choices=['upstream', 'downstream', 'both'],
                   help='upstream = who depends on it (default); '
                        'downstream = what it depends on')
    p.add_argument('--include-rel', action='append')
    p.add_argument('--exclude-rel', action='append')
    p.add_argument('--all-matches', action='store_true')
    p.add_argument('--fail-on', default='NONE',
                   choices=['NONE', 'MEDIUM', 'HIGH', 'CRITICAL'])
    p.add_argument('--json', action='store_true')
    p.add_argument('--save', help='Write .md/.json/.mmd next to this path stem')
    p.set_defaults(func=cmd_impact)

    p = sub.add_parser('rules', help='List rule findings')
    p.add_argument('--category', choices=['SECURITY', 'PERFORMANCE', 'CORRECTNESS',
                                          'MAINTAINABILITY', 'TECH_DEBT'])
    p.add_argument('--rule', help='One rule id, e.g. SEC-002')
    p.add_argument('--min-severity', default='LOW', choices=SEVERITY_ORDER)
    p.add_argument('--fail-on', choices=SEVERITY_ORDER,
                   help='Exit 2 when a finding at this severity or above exists')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser('diagrams', help='Generate Mermaid / PlantUML diagram sources')
    p.add_argument('--format', default='both', choices=['mermaid', 'plantuml', 'both'])
    p.add_argument('--diagram-dir')
    p.set_defaults(func=cmd_diagrams)

    p = sub.add_parser('context', help='Write LLM grounding packs')
    p.set_defaults(func=cmd_context)

    p = sub.add_parser('report', help='Scaffold the analysis reports')
    p.add_argument('--reports-dir')
    p.set_defaults(func=cmd_report)

    p = sub.add_parser('queries', help='Emit the Cypher query cookbook')
    p.add_argument('--print-queries', action='store_true')
    p.set_defaults(func=cmd_queries)

    p = sub.add_parser('diff', help='Compare this graph with an earlier release')
    p.add_argument('--baseline', required=True, help='Path to the earlier graph.json')
    p.add_argument('--json', action='store_true')
    p.add_argument('--save')
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser('all', help='Run the whole pipeline')
    _analyze_arguments(p)
    p.add_argument('--strict', action='store_true')
    p.add_argument('--format', default='both', choices=['mermaid', 'plantuml', 'both'])
    p.add_argument('--diagram-dir')
    p.add_argument('--reports-dir')
    p.set_defaults(func=cmd_all)
    return parser


def _analyze_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--source', '-s', required=True,
                        help='APEX export root (split export directory, f100.sql, '
                             'or a directory holding both the export and its DDL)')
    parser.add_argument('--app-id', type=int, help='Application id (inferred if omitted)')
    parser.add_argument('--schema', help='Parsing schema (inferred from the export '
                                         'if omitted)')
    parser.add_argument('--db-meta', help='db_meta.json from apex_analyzer/extract')
    parser.add_argument('--apex-meta', help='apex_meta.json from apex_analyzer/extract')
    parser.add_argument('--git', action='store_true',
                        help='Record repository, branch and commit history')
    parser.add_argument('--git-range', help='Commit range for the change layer, '
                                            'e.g. v1.2..HEAD (implies --git)')


def main(argv: Optional[List[str]] = None) -> int:
    global logger
    parser = build_parser()
    args = parser.parse_args(argv)
    logger = setup_logging(args.verbose, 'apex_analyzer')
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
