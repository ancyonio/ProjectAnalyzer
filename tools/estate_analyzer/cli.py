"""Command line interface.

    estate-analyze federate  --tibco <dir> --apex <dir> --oracle <dir>
                             [--estate-map estate_map.json] [--allow-name-match]
    estate-analyze validate  [--strict]
    estate-analyze links     [--basis qualified-name] [--json]
    estate-analyze inventory [--json]
    estate-analyze findings  [--category CROSS_ESTATE] [--estate tibco]
    estate-analyze impact    --target "DbTable:ORDERS" [--direction upstream]
    estate-analyze sequence  [--json]
    estate-analyze diagrams  [--format mermaid]
    estate-analyze context   (LLM grounding packs)
    estate-analyze report    (report scaffolds)
    estate-analyze queries   (Cypher cookbook)
    estate-analyze all       --tibco <dir> --apex <dir> --oracle <dir>

`federate` is the only command that reads the three upstream graphs, and it is
read-only: it parses no source and writes nothing into their output
directories. Everything else reads `<output>/graph.json`.

Exit codes: 0 ok, 1 usage or runtime error, 2 gate failure (use in CI).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from analyzer_core.analysis.impact import ImpactAnalyzer
from analyzer_core.analysis.impact import render_markdown as impact_markdown
from analyzer_core.analysis.impact import render_mermaid as impact_mermaid
from analyzer_core.cli_base import load_graph, print_stats, setup_logging, write
from analyzer_core.graph.exporters import Neo4jExporter
from analyzer_core.graph.validate import GraphValidator
from analyzer_core.graph.validate import render_markdown as validation_markdown
from analyzer_core.model import Graph

from .analysis.inventory import full_inventory, issues_summary
from .analysis.rules_catalog import apply_rules
from .analysis.sequence import render_markdown as sequence_markdown
from .analysis.sequence import sequence
from .constants import (CATEGORIES, DEFAULT_OUTPUT_DIRS, ESTATES,
                        MIN_DATASOURCE_COVERAGE, MIN_SQL_BIND_COVERAGE,
                        SEVERITY_ORDER)
from .federate import federate, load_estate_map, load_sources
from .graph.queries import render_cookbook
from .graph.queries import render_markdown as queries_markdown
from .graph.schema import impact_config, neo4j_schema, validation_config
from .links import link_estates

DEFAULT_OUTPUT = 'analysis_output_estate'
GRAPH_FILE = 'graph.json'
LINKS_FILE = 'links.json'

logger = None


# ──────────────────────────────────────────────────────────────
def _estate_paths(args: argparse.Namespace) -> Dict[str, Path]:
    paths: Dict[str, Path] = {}
    for estate in ESTATES:
        value = getattr(args, estate, None)
        if value:
            paths[estate] = Path(value)
    return paths


def _print_next(args: argparse.Namespace) -> None:
    """Say what `federate` wrote, and what it did not."""
    if getattr(args, 'running_all', False):
        return
    print(f'\n  Next: estate-analyze -o {args.output} validate')
    print('\n  `federate` writes the graph, the link report and the Neo4j export')
    print('  only. It does not write context/, generated_diagrams/ or reports/.')
    print(f'\n    estate-analyze -o {args.output} all '
          + ' '.join(f'--{estate} {path}'
                     for estate, path in _estate_paths(args).items()))
    print('\n  or run the parts you need: estate-analyze context | diagrams | '
          'report\n')


def cmd_federate(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    sources = load_sources(_estate_paths(args))
    estate_map = load_estate_map(Path(args.estate_map) if args.estate_map else None)

    graph, federation = federate(sources)
    link_result = link_estates(graph, federation, estate_map,
                               allow_name_match=args.allow_name_match)
    issue_count = apply_rules(graph, federation, link_result)

    graph.meta['coverage'].update(link_result['coverage'])
    graph.meta['links'] = {
        'linkCount': len(link_result['links']),
        'suppressedCount': len(link_result['suppressed']),
        'unboundCount': len(link_result['unbound']),
        'estateMap': str(args.estate_map or ''),
        'allowNameMatch': bool(args.allow_name_match),
    }
    graph.meta['issueCount'] = issue_count
    graph.save(output_dir / GRAPH_FILE)
    write(output_dir / LINKS_FILE, json.dumps(link_result, indent=2, default=str),
          logger)

    files = Neo4jExporter(graph, output_dir, neo4j_schema()).write_all()
    files['links'] = str(output_dir / LINKS_FILE)
    print_stats(graph, 'FEDERATED ESTATE KNOWLEDGE GRAPH', output_dir, files)

    coverage = graph.meta['coverage']
    print('\n  ESTATES:')
    for estate, info in graph.meta['estates'].items():
        print(f"   {estate:8} {info['nodes']:6,} nodes  {info['relationships']:6,} rels"
              f"  {info['sourceRoot'] or info['outputDir']}")

    print('\n  CROSS-ESTATE JOIN:')
    print(f"   shared database nodes    : {coverage['mergedDbNodes']} (exact, no heuristic)")
    print(f"   inferred links added     : {coverage['crossEstateLinks']}"
          f"  {coverage['crossEstateLinksByBasis'] or ''}")
    print(f"   suppressed name matches  : {len(link_result['suppressed'])}")
    print(f"   SQL bind coverage        : {coverage['sqlBindCoverage']}%"
          f"  ({coverage['jdbcActivitiesBound']}/{coverage['jdbcActivitiesWithSql']}"
          f" JDBC activities with static SQL)")
    print(f"   datasource coverage      : {coverage['datasourceCoverage']}%"
          f"  ({coverage['datasourcesMapped']}/{coverage['datasources']} mapped)")
    print(f"   no static SQL            : {coverage['noStaticSqlSites']} activity/ies")
    print(f"   unbound references       : {coverage['unboundReferences']}")
    print(f"   cross-estate findings    : {issue_count}")

    if coverage['sqlBindCoverage'] < MIN_SQL_BIND_COVERAGE:
        print(f'\n  SQL bind coverage is below {MIN_SQL_BIND_COVERAGE}%: the '
              f'cross-estate view is provisional\n  and every answer drawn from '
              f'it must say so. See {output_dir / LINKS_FILE}.')
    if coverage['datasourceCoverage'] < MIN_DATASOURCE_COVERAGE:
        print(f'\n  {coverage["datasources"] - coverage["datasourcesMapped"]} JDBC '
              f'datasource(s) have no estate-map entry, so every table reached\n'
              f'  through them is missing from this graph.')
    _print_next(args)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    graph = load_graph(output_dir, hint='federate')
    result = GraphValidator(graph, validation_config(), output_dir).run()
    write(output_dir / 'validation_report.md',
          validation_markdown(result, 'Federated Estate Validation Report'), logger)
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


def cmd_links(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    path = output_dir / LINKS_FILE
    if not path.exists():
        raise FileNotFoundError(f'{path} not found. Run `federate` first.')
    with open(path, encoding='utf-8') as handle:
        result = json.load(handle)

    links = [row for row in result['links']
             if not args.basis or row['basis'] == args.basis]
    if args.json:
        print(json.dumps({'links': links, 'suppressed': result['suppressed'],
                          'unbound': result['unbound'],
                          'datasources': result['datasources'],
                          'coverage': result['coverage']}, indent=2))
        return 0

    print(f"\n{len(links)} cross-estate link(s)\n")
    for row in links:
        print(f"  {row['fromLabel']}:{row['fromName']:<28} "
              f"-{row['relType']:<14}-> {row['toLabel']}:{row['toName']:<20} "
              f"[{row['basis']} {row['confidence']}]")

    if result['suppressed']:
        print(f"\n{len(result['suppressed'])} suppressed match(es) "
              f"(re-run federate with --allow-name-match to admit them):")
        for row in result['suppressed']:
            print(f"  {row['fromName']:<28} -{row['relType']:<14}-> "
                  f"{row['toName']:<20} [{row['basis']}]")

    if result['unbound']:
        print(f"\n{len(result['unbound'])} unbound reference(s):")
        for row in result['unbound']:
            table = row.get('table', '')
            print(f"  {row['activity']:<28} {table:<20} {row['reason']}")
            print(f"      {row['detail']}")

    print('\nDatasources:')
    for row in result['datasources']:
        state = f"-> {row['schema']}" if row['mapped'] else 'UNMAPPED'
        print(f"  {row['name']:<38} {state:<16} {row['url']}")
    print()
    return 0


def cmd_inventory(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    graph = load_graph(output_dir, hint='federate')
    inventory = full_inventory(graph)
    if args.json:
        print(json.dumps(inventory, indent=2, default=str))
        return 0

    summary = inventory['summary']
    print('\n' + '=' * 66)
    print('  FEDERATED ESTATE INVENTORY')
    print('=' * 66)
    print('\n  SIZE:')
    for key in ('estates', 'nodes', 'relationships', 'tibcoProcesses',
                'tibcoActivities', 'apexPages', 'oracleProgramUnits',
                'databaseObjects', 'sharedDatabaseObjects',
                'sharedDatabaseNodes', 'crossEstateLinks', 'contendedTables',
                'issues'):
        print(f'   {key:24} : {summary[key]:6,}')

    print('\n  ESTATES:')
    for row in inventory['estates']:
        print(f"   {row['estate']:8} {row['nodes']:6,} nodes  "
              f"coverage {row['coverage']:<22} {row['sourceRoot']}")

    contended = inventory['contendedTables']
    print(f'\n  CONTENDED TABLES ({len(contended)}):')
    for row in contended:
        print(f"   {row['name']:28} written by "
              f"{', '.join(row['writerEstates'])}"
              f"  read by {', '.join(row['readerEstates']) or '-'}")

    print('\n  COMPONENTS REACHING ACROSS AN ESTATE BOUNDARY:')
    for row in inventory['boundaryComponents'][:15]:
        print(f"   {row['estate']:7} {row['label']:14} {row['name']:26} "
              f"-> {', '.join(row['reaches'])}")

    issues = inventory['issues']
    print(f"\n  FINDINGS: {issues['total']} "
          f"({', '.join(f'{k}={v}' for k, v in issues['bySeverity'].items())})")
    print(f"\n  Full detail: {output_dir / 'inventory.json'}\n")
    write(output_dir / 'inventory.json',
          json.dumps(inventory, indent=2, default=str), logger)
    return 0


def cmd_findings(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    graph = load_graph(output_dir, hint='federate')
    summary = issues_summary(graph)

    minimum = SEVERITY_ORDER.index(args.min_severity) if args.min_severity else 0
    findings = [f for f in summary['findings']
                if f['severity'] in SEVERITY_ORDER
                and SEVERITY_ORDER.index(f['severity']) >= minimum
                and (not args.category or f['category'] == args.category)
                and (not args.estate or f['estate'] == args.estate)
                and (not args.rule or f['ruleId'] == args.rule)]
    suppressed = len(summary['findings']) - len(findings)

    if args.json:
        print(json.dumps({'total': len(findings),
                          'totalBeforeFilter': len(summary['findings']),
                          'suppressedByFilter': suppressed,
                          'byEstate': summary['byEstate'],
                          'findings': findings}, indent=2))
    else:
        print(f'\n{len(findings)} finding(s)\n')
        for finding in findings:
            where = f" ({finding['filePath']})" if finding['filePath'] else ''
            print(f"  [{finding['severity']:<8}] {finding['ruleId']}: "
                  f"{finding['description']}{where}")
        print('\nBy severity:', summary['bySeverity'])
        print('By estate  :', summary['byEstate'])
        if suppressed:
            print(f'({suppressed} further finding(s) hidden by the active filter; '
                  f"{len(summary['findings'])} in the graph)")

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
    graph = load_graph(output_dir, hint='federate')
    targets = _resolve_targets(graph, args.target)
    result = ImpactAnalyzer(graph, impact_config()).analyze(
        targets, depth=args.depth, direction=args.direction)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(impact_markdown(result))
        print(_estate_breakdown(graph, result))
    if args.save:
        write(Path(args.save), impact_markdown(result), logger)
        write(Path(args.save).with_suffix('.mmd'), impact_mermaid(result), logger)
    if args.fail_on and result['summary'].get('riskBand') == args.fail_on:
        return 2
    return 0


def _estate_breakdown(graph: Graph, result: dict) -> str:
    """Which estates a blast radius crosses -- the federated question."""
    counts: Dict[str, int] = {}
    for row in result['impacted']:
        node = graph.nodes.get(row['nodeId'])
        estate = str(node.properties.get('estate', '')) if node else ''
        if estate:
            counts[estate] = counts.get(estate, 0) + 1
    if not counts:
        return ''
    lines = ['', '## Impact by estate', '', '| Estate | Impacted nodes |', '|---|---|']
    for estate, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        lines.append(f'| {estate} | {count} |')
    if len(counts) > 1:
        lines += ['', f'This change crosses {len(counts)} estates. No '
                      'single-estate analysis would have shown that.']
    return '\n'.join(lines) + '\n'


def cmd_sequence(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    graph = load_graph(output_dir, hint='federate')
    result = sequence(graph)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(sequence_markdown(result))
    if args.save:
        write(Path(args.save), sequence_markdown(result), logger)
    return 0


def cmd_diagrams(args: argparse.Namespace) -> int:
    from .diagrams import mermaid
    output_dir = Path(args.output)
    graph = load_graph(output_dir, hint='federate')
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
    graph = load_graph(output_dir, hint='federate')
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
    graph = load_graph(output_dir, hint='federate')
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
    rc = cmd_federate(args)
    if rc:
        return rc
    args.strict = False
    validate_rc = cmd_validate(args)
    args.diagram_dir = None
    cmd_diagrams(args)
    cmd_context(args)
    cmd_report(args)
    cmd_queries(args)
    args.json = False
    cmd_inventory(args)
    args.save = None
    cmd_sequence(args)
    args.category = args.estate = args.rule = None
    args.min_severity = 'MEDIUM'
    args.fail_on = None
    cmd_findings(args)
    print(f'\nPipeline complete. Load the graph with '
          f'`python scripts/push_to_neo4j.py -o {args.output}`.')
    return validate_rc


# ──────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='estate-analyze',
        description='Read-only cross-estate federation over finished TIBCO, '
                    'Oracle APEX and Oracle PL/SQL knowledge graphs.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    parser.add_argument('--output', '-o', default=DEFAULT_OUTPUT,
                        help=f'Analysis output directory (default: {DEFAULT_OUTPUT})')
    parser.add_argument('--verbose', '-v', action='store_true')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('federate', help='Join the three graphs into one')
    _federate_args(p)
    p.set_defaults(func=cmd_federate)

    p = sub.add_parser('validate', help='Integrity and coverage gate')
    p.add_argument('--strict', action='store_true',
                   help='Treat warnings as failures (exit 2)')
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser('links', help='Every cross-estate link and its evidence')
    p.add_argument('--basis', choices=['exact', 'declared', 'qualified-name', 'name'])
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_links)

    p = sub.add_parser('inventory', help='Estate-wide inventory')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser('findings', help='The merged, namespaced findings ledger')
    p.add_argument('--category', choices=list(CATEGORIES))
    p.add_argument('--estate', choices=list(ESTATES) + ['cross'])
    p.add_argument('--rule', help='Single rule id, e.g. XE-001 or APEX.SEC-001')
    p.add_argument('--min-severity', default='LOW', choices=SEVERITY_ORDER)
    p.add_argument('--fail-on', choices=SEVERITY_ORDER,
                   help='Exit 2 when a finding at or above this severity exists')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_findings)

    p = sub.add_parser('impact', help='Blast radius across every estate')
    p.add_argument('--target', action='append', required=True,
                   help='"Label:Name", a node id, or a name')
    p.add_argument('--direction', default='upstream',
                   choices=['upstream', 'downstream', 'both'])
    p.add_argument('--depth', type=int, default=8)
    p.add_argument('--fail-on', choices=['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'])
    p.add_argument('--save', help='Write the report to this path')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_impact)

    p = sub.add_parser('sequence', help='Modernisation order across the estates')
    p.add_argument('--save', help='Write the report to this path')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_sequence)

    p = sub.add_parser('diagrams', help='Mermaid diagram sources')
    p.add_argument('--diagram-dir')
    p.set_defaults(func=cmd_diagrams)

    p = sub.add_parser('context', help='LLM grounding packs')
    p.set_defaults(func=cmd_context)

    p = sub.add_parser('report', help='Report scaffolds')
    p.set_defaults(func=cmd_report)

    p = sub.add_parser('queries', help='Cypher cookbook')
    p.set_defaults(func=cmd_queries)

    p = sub.add_parser('all', help='federate + validate + everything else')
    _federate_args(p)
    p.set_defaults(func=cmd_all)
    return parser


def _federate_args(parser: argparse.ArgumentParser) -> None:
    for estate in ESTATES:
        parser.add_argument(f'--{estate}',
                            help=f'{estate} analyzer output directory '
                                 f'(e.g. {DEFAULT_OUTPUT_DIRS[estate]})')
    parser.add_argument('--estate-map',
                        help='Operator-declared datasource to schema mapping. '
                             'A JDBC url names a database, not a schema, so '
                             'this is never inferred.')
    parser.add_argument('--allow-name-match', action='store_true',
                        help='Admit bare-name table matches (confidence 0.5). '
                             'Off by default; suppressed matches are always '
                             'reported either way.')


def main(argv: Optional[List[str]] = None) -> int:
    global logger
    parser = build_parser()
    args = parser.parse_args(argv)
    logger = setup_logging(args.verbose, 'estate_analyzer')
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
