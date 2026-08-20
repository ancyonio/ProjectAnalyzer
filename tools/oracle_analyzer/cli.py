"""Command line interface.

    oracle-analyze analyze   --source <repo_root> [--schema ORDER_APP]
                             [--db-meta db_meta.json] [--business-map map.json]
    oracle-analyze validate  [--strict]
    oracle-analyze inventory [--json]
    oracle-analyze rules     [--category SECURITY] [--min-severity HIGH]
    oracle-analyze impact    --target "DbTable:ORDERS" [--direction upstream]
    oracle-analyze lineage   --target "DbTable:ORDERS"
    oracle-analyze diagrams  [--format mermaid]
    oracle-analyze context   (LLM grounding packs)
    oracle-analyze report    (report scaffolds)
    oracle-analyze queries   (Cypher cookbook)
    oracle-analyze all       --source <repo_root>

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

from .analysis.inventory import full_inventory, issues_summary
from .analysis.lineage import lineage, render_markdown as lineage_markdown
from .analyzer import OracleAnalyzer
from .constants import SEVERITY_ORDER
from .graph.queries import render_cookbook
from .graph.queries import render_markdown as queries_markdown
from .graph.schema import impact_config, neo4j_schema, validation_config

DEFAULT_OUTPUT = 'analysis_output_oracle'
GRAPH_FILE = 'graph.json'

logger = None


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
    analyzer = OracleAnalyzer(args.source, output_dir,
                              default_owner=args.schema or '',
                              db_meta=Path(args.db_meta) if args.db_meta else None,
                              business_map=Path(args.business_map)
                              if args.business_map else None)
    graph = analyzer.analyze()
    graph.save(output_dir / GRAPH_FILE)

    files = Neo4jExporter(graph, output_dir, neo4j_schema()).write_all()
    write(output_dir / 'inventory.json',
          json.dumps(full_inventory(graph), indent=2, default=str), logger)

    print_stats(graph, 'ORACLE PL/SQL KNOWLEDGE GRAPH', output_dir, files)

    coverage = graph.meta['coverage']
    print('\n  COVERAGE:')
    print(f"   dictionary available     : {coverage['dictionaryAvailable']}")
    print(f"   objects modelled         : {coverage['objectsModelled']}"
          f"/{coverage['objectsDiscovered']}"
          f" ({coverage['resolutionCoverage']}%)")
    print(f"   calls resolved           : {coverage['callsResolved']}"
          f"/{coverage['callsResolved'] + coverage['callsUnresolved']}"
          f" ({coverage['callResolution']}%)")
    print(f"   dynamic SQL sites        : {coverage['dynamicSqlSites']}")
    print(f"   code parsed              : {coverage['statementsParsed']}"
          f"/{coverage['codeNodes']}"
          f" ({coverage['parseQuality']}%)"
          f"  partial={coverage['statementsPartial']}"
          f" failed={coverage['statementsFailed']}")
    print(f"   DDL statements parsed    : "
          f"{coverage['ddlStatements'] - coverage['ddlUnparsed']}"
          f"/{coverage['ddlStatements']}"
          f"  unparsed={coverage['ddlUnparsed']}")
    if coverage['resolutionCoverage'] < 80:
        print('\n  Resolution is below 80%: the graph is provisional and every '
              'answer drawn from it must say so.')
    if coverage['parseQuality'] < 90:
        print('\n  Parse quality is below 90%: the names that did bind may still '
              'be an incomplete picture of what the code does.')
    _print_next('oracle-analyze', args)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    graph = load_graph(output_dir)
    result = GraphValidator(graph, validation_config(), output_dir).run()
    write(output_dir / 'validation_report.md',
          validation_markdown(result, 'Oracle Graph Validation Report'), logger)
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


def cmd_inventory(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    graph = load_graph(output_dir)
    inventory = full_inventory(graph)

    if args.json:
        print(json.dumps(inventory, indent=2, default=str))
        return 0

    summary = inventory['summary']
    coverage = inventory['coverage']
    print('\n' + '=' * 66)
    print('  ORACLE ESTATE INVENTORY')
    print('=' * 66)
    print('\n  SIZE:')
    for key in ('schemas', 'tables', 'columns', 'views', 'packages',
                'programUnits', 'triggers', 'sequences', 'synonyms',
                'sqlStatements', 'files'):
        print(f'   {key:24} : {summary[key]:6,}')

    print('\n  COVERAGE:')
    print(f"   resolution               : {coverage.get('resolutionCoverage')}%")
    print(f"   call resolution          : {coverage.get('callResolution')}%")
    print(f"   dynamic SQL sites        : {coverage.get('dynamicSqlSites')}")
    print(f"   parse quality            : {coverage.get('parseQuality')}%")
    print(f"   unresolved references    : {summary['unresolvedReferences']}")

    if inventory['schemas']:
        print('\n  SCHEMAS:')
        for row in inventory['schemas']:
            print(f"   {row['name']:24} tables={row['tables']:<4} "
                  f"views={row['views']:<4} packages={row['packages']:<4} "
                  f"triggers={row['triggers']}")

    if inventory['packages']:
        print('\n  PACKAGES:')
        for row in inventory['packages']:
            halves = ('spec+body' if row['hasSpec'] and row['hasBody']
                      else 'spec only' if row['hasSpec'] else 'body only')
            print(f"   {row['name']:28} {halves:<10} units={row['units']:<4} "
                  f"loc={row['loc']:<6} fanIn={row['fanIn']}")

    if inventory['complexity']:
        print('\n  MOST COMPLEX UNITS:')
        for row in inventory['complexity'][:10]:
            name = f"{row['package']}.{row['name']}" if row['package'] else row['name']
            print(f"   {name:38} {row['tier']:<8} score={row['complexity']:<6} "
                  f"loc={row['loc']}")

    if inventory['hotspots']:
        print('\n  MOST DEPENDED-UPON:')
        for row in inventory['hotspots'][:10]:
            print(f"   {row['label']:16} {row['name']:28} dependents={row['fanIn']}")

    issues = inventory['issues']
    print(f"\n  FINDINGS: {issues['total']} "
          f"({', '.join(f'{k}={v}' for k, v in sorted(issues['bySeverity'].items()))})")
    print(f"\n  Full detail: {output_dir / 'inventory.json'}\n")
    return 0


def cmd_rules(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    graph = load_graph(output_dir)
    summary = issues_summary(graph)

    minimum = SEVERITY_ORDER.index(args.min_severity) if args.min_severity else 0
    findings = [f for f in summary['findings']
                if f['severity'] in SEVERITY_ORDER
                and SEVERITY_ORDER.index(f['severity']) >= minimum
                and (not args.category or f['category'] == args.category)
                and (not args.rule or f['ruleId'] == args.rule)]

    shown = {sev: sum(1 for f in findings if f['severity'] == sev)
             for sev in SEVERITY_ORDER}
    shown = {sev: n for sev, n in shown.items() if n}
    suppressed = len(summary['findings']) - len(findings)

    if args.json:
        print(json.dumps({'total': len(findings), 'bySeverity': shown,
                          'totalBeforeFilter': len(summary['findings']),
                          'suppressedByFilter': suppressed,
                          'findings': findings}, indent=2))
    else:
        print(f'\n{len(findings)} finding(s)\n')
        for finding in findings:
            where = f" ({finding['filePath']}:{finding['lineStart']})" \
                if finding['filePath'] else ''
            print(f"  [{finding['severity']:<8}] {finding['ruleId']}: "
                  f"{finding['description']}{where}")
        print('\nBy severity:', shown)
        if suppressed:
            print(f'({suppressed} further finding(s) hidden by the active '
                  f"filter; {len(summary['findings'])} in the graph)")

    if args.fail_on and args.fail_on in SEVERITY_ORDER:
        threshold = SEVERITY_ORDER.index(args.fail_on)
        if any(SEVERITY_ORDER.index(f['severity']) >= threshold
               for f in findings if f['severity'] in SEVERITY_ORDER):
            return 2
    return 0


def _resolve_targets(graph: Graph, refs: List[str]):
    targets = []
    for ref in refs:
        matches = graph.resolve(ref)
        if not matches:
            raise ValueError(f"no component matches '{ref}'")
        if len(matches) > 1:
            names = ', '.join(f'{m.label}:{m.name}' for m in matches[:6])
            raise ValueError(f"'{ref}' is ambiguous: {names}")
        targets.append(matches[0])
    return targets


def cmd_impact(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    graph = load_graph(output_dir)
    targets = _resolve_targets(graph, args.target)

    result = ImpactAnalyzer(graph, impact_config()).analyze(
        targets, depth=args.depth, direction=args.direction)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(impact_markdown(result))
    if args.save:
        write(Path(args.save), impact_markdown(result), logger)
        write(Path(args.save).with_suffix('.mmd'), impact_mermaid(result), logger)
    if args.fail_on and result.get('riskBand') == args.fail_on:
        return 2
    return 0


def cmd_lineage(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    graph = load_graph(output_dir)
    targets = _resolve_targets(graph, [args.target])
    result = lineage(graph, targets[0])

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(lineage_markdown(result))
    if args.save:
        write(Path(args.save), lineage_markdown(result), logger)
    return 0


def cmd_diagrams(args: argparse.Namespace) -> int:
    from .diagrams import mermaid
    output_dir = Path(args.output)
    graph = load_graph(output_dir)
    target_dir = Path(args.diagram_dir) if args.diagram_dir \
        else output_dir / 'generated_diagrams'
    produced = mermaid.generate_all(graph)
    for name, content in produced.items():
        write(target_dir / name, content, logger)
    print(f'\n{len(produced)} diagram source(s) written to {target_dir}')
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    from .report.contextpack import generate_all
    output_dir = Path(args.output)
    graph = load_graph(output_dir)
    target_dir = output_dir / 'context'
    packs = generate_all(graph)
    for name, content in packs.items():
        write(target_dir / name, content, logger)
    print(f'\n{len(packs)} context pack(s) written to {target_dir}')
    for name in sorted(packs):
        print(f'  {name}')
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .report.reports import generate_all
    output_dir = Path(args.output)
    graph = load_graph(output_dir)
    target_dir = output_dir / 'reports'
    reports = generate_all(graph)
    for name, content in reports.items():
        write(target_dir / name, content, logger)
    write(target_dir / 'inventory.json',
          json.dumps(full_inventory(graph), indent=2, default=str), logger)
    print(f'\nReports scaffolded in {target_dir}:')
    for name in sorted(reports):
        print(f'  {name}')
    print('\nSections marked `<!-- LLM: ... -->` are for the agent to complete.')
    return 0


def cmd_queries(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    write(output_dir / 'analysis_queries.cypher', render_cookbook(), logger)
    write(output_dir / 'ANALYSIS_QUERIES.md', queries_markdown(), logger)
    print(f"\nCypher cookbook written to {output_dir / 'analysis_queries.cypher'}")
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    args.running_all = True
    rc = cmd_analyze(args)
    if rc:
        return rc
    args.strict = False
    validate_rc = cmd_validate(args)
    args.diagram_dir = None
    cmd_diagrams(args)
    cmd_context(args)
    cmd_report(args)
    cmd_queries(args)
    args.category = args.rule = None
    args.min_severity = 'MEDIUM'
    args.fail_on = None
    args.json = False
    cmd_rules(args)
    print(f'\nPipeline complete. Load the graph with '
          f'`python scripts/push_to_neo4j.py -o {args.output}`.')
    return validate_rc


# ──────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='oracle-analyze',
        description='Deterministic Oracle PL/SQL analysis: knowledge graph, '
                    'inventory, data lineage, blast radius and rule findings.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    parser.add_argument('--output', '-o', default=DEFAULT_OUTPUT,
                        help=f'Analysis output directory (default: {DEFAULT_OUTPUT})')
    parser.add_argument('--verbose', '-v', action='store_true')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('analyze', help='Parse an Oracle source tree into a graph')
    _source_args(p)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser('validate', help='Integrity and completeness gate')
    p.add_argument('--strict', action='store_true',
                   help='Treat warnings as failures (exit 2)')
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser('inventory', help='Estate inventory from the graph')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser('rules', help='Rule findings')
    p.add_argument('--category', choices=['SECURITY', 'PERFORMANCE',
                                          'CORRECTNESS', 'DEBT'])
    p.add_argument('--rule', help='Single rule id, e.g. SEC-001')
    p.add_argument('--min-severity', default='LOW', choices=SEVERITY_ORDER)
    p.add_argument('--fail-on', choices=SEVERITY_ORDER,
                   help='Exit 2 when a finding at or above this severity exists')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser('impact', help='Blast radius of a change')
    p.add_argument('--target', action='append', required=True,
                   help='"Label:Name", a node id, or a name')
    p.add_argument('--direction', default='upstream',
                   choices=['upstream', 'downstream', 'both'])
    p.add_argument('--depth', type=int, default=8)
    p.add_argument('--fail-on', choices=['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'])
    p.add_argument('--save', help='Write the report to this path')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_impact)

    p = sub.add_parser('lineage', help='Where a table is written and read')
    p.add_argument('--target', required=True, help='"DbTable:ORDERS"')
    p.add_argument('--save', help='Write the report to this path')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_lineage)

    p = sub.add_parser('diagrams', help='Mermaid diagram sources')
    p.add_argument('--diagram-dir')
    p.set_defaults(func=cmd_diagrams)

    p = sub.add_parser('context', help='LLM grounding packs')
    p.set_defaults(func=cmd_context)

    p = sub.add_parser('report', help='Report scaffolds')
    p.set_defaults(func=cmd_report)

    p = sub.add_parser('queries', help='Cypher cookbook')
    p.set_defaults(func=cmd_queries)

    p = sub.add_parser('all', help='analyze + validate + everything else')
    _source_args(p)
    p.set_defaults(func=cmd_all)
    return parser


def _source_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--source', required=True,
                        help='Root of the Oracle source repository')
    parser.add_argument('--schema',
                        help='Default owner for unqualified objects, '
                             'e.g. ORDER_APP')
    parser.add_argument('--db-meta',
                        help='db_meta.json data-dictionary extract '
                             '(authoritative where present)')
    parser.add_argument('--business-map',
                        help='JSON map of declared business domains and '
                             'functions; overrides the derived seed')


def main(argv: Optional[List[str]] = None) -> int:
    global logger
    parser = build_parser()
    args = parser.parse_args(argv)
    logger = setup_logging(args.verbose, 'oracle_analyzer')
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
