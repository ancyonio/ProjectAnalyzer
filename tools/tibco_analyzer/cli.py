"""Command line interface.

    tibco-analyze analyze   --source <tibco_root> [--output <dir>]
    tibco-analyze validate  [--strict]
    tibco-analyze index     [--no-embeddings] [--provider auto|sentence-transformers|openai|azure-openai]
    tibco-analyze search    "<question>" [--label BWProcess] [--module M] [--top 10] [--json]
    tibco-analyze impact    --target "XSD:Order.xsd" [--depth 4] [--direction upstream]
    tibco-analyze diagrams  [--format mermaid|plantuml|both]
    tibco-analyze context   (LLM grounding packs)
    tibco-analyze report    (Step00/01/02 scaffolds)
    tibco-analyze queries   (Cypher cookbook)
    tibco-analyze all       --source <tibco_root>   (everything, in order)

Every command except `analyze` reads `<output>/graph.json`, so the expensive
parse happens once. Exit codes: 0 ok, 1 usage/runtime error, 2 validation
failure (use in CI).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .analysis.impact import ImpactAnalyzer, render_markdown as impact_markdown
from .analysis.impact import render_mermaid as impact_mermaid
from .analysis.inventory import full_inventory
from .analyzer import TibcoAnalyzer
from .diagrams import mermaid, plantuml
from .graph.exporters import Neo4jExporter
from .graph.queries import render_cookbook, render_markdown as queries_markdown
from .graph.validate import GraphValidator, render_markdown as validation_markdown
from .model import Graph
from .report.contextpack import ContextPackBuilder
from .report.reports import generate_reports
from .search.engine import SearchEngine, render_markdown as search_markdown

DEFAULT_OUTPUT = 'analysis_output'
GRAPH_FILE = 'graph.json'
INDEX_DIRNAME = 'search_index'

logger = logging.getLogger('tibco_analyzer')


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format='%(asctime)s | %(levelname)-7s | %(message)s',
        datefmt='%H:%M:%S',
    )


def _load_graph(output_dir: Path) -> Graph:
    return Graph.load(output_dir / GRAPH_FILE)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    logger.info("Wrote %s", path)
    return path


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
    analyzer = TibcoAnalyzer(args.source, output_dir)
    graph = analyzer.analyze()
    graph.save(output_dir / GRAPH_FILE)

    files = Neo4jExporter(graph, output_dir).write_all()
    _write(output_dir / 'analysis_queries.cypher', render_cookbook())
    _write(output_dir / 'ANALYSIS_QUERIES.md', queries_markdown())

    stats = graph.stats()
    print('\n' + '=' * 66)
    print('  TIBCO KNOWLEDGE GRAPH BUILT')
    print('=' * 66)
    print(f"\n  Nodes         : {stats['totalNodes']:,}")
    print(f"  Relationships : {stats['totalRelationships']:,}")
    print('\n  NODE COUNTS:')
    for label, count in stats['nodeCounts'].items():
        print(f"   {label:22} : {count:6,}")
    print('\n  RELATIONSHIP COUNTS:')
    for rtype, count in stats['relationshipCounts'].items():
        print(f"   {rtype:22} : {count:6,}")
    print('\n  OUTPUT:')
    print(f"   graph.json               : {output_dir / GRAPH_FILE}")
    for name, path in files.items():
        print(f"   {name:24} : {path}")
    _print_next('tibco-analyze', args)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    graph = _load_graph(output_dir)
    result = GraphValidator(graph, output_dir).run()
    _write(output_dir / 'validation_report.md', validation_markdown(result))
    _write(output_dir / 'validation_report.json', json.dumps(result, indent=2))

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


def cmd_index(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    graph = _load_graph(output_dir)
    source = args.source or (graph.meta or {}).get('tibcoRoot')
    engine = SearchEngine(graph, output_dir / INDEX_DIRNAME,
                          Path(source) if source else None,
                          embedding_provider=args.provider)
    info = engine.build(use_embeddings=not args.no_embeddings)
    print(json.dumps(info, indent=2))
    if not info['vectorSearch']:
        print('\nNote: running lexical-only (BM25). For vector search install '
              '`sentence-transformers`, or set OPENAI_API_KEY / AZURE_OPENAI_API_KEY, '
              'then re-run `index`.')
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    graph = _load_graph(output_dir)
    engine = SearchEngine(graph, output_dir / INDEX_DIRNAME,
                          embedding_provider=args.provider)
    engine.load()
    result = engine.search(args.query, top_k=args.top,
                           labels=args.label, modules=args.module)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(search_markdown(result))
    if args.save:
        _write(Path(args.save), search_markdown(result))
    return 0


def cmd_impact(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    graph = _load_graph(output_dir)

    targets = []
    for ref in args.target:
        matches = graph.resolve(ref, label=args.label[0] if args.label else None)
        if not matches:
            print(f"ERROR: no artefact matches '{ref}'. Try `tibco-analyze search \"{ref}\"`.",
                  file=sys.stderr)
            return 1
        if len(matches) > 1 and not args.all_matches:
            print(f"Ambiguous target '{ref}' — {len(matches)} matches:", file=sys.stderr)
            for m in matches[:15]:
                print(f"  {m.label}:{m.name}  (id {m.node_id}, {m.file_path})", file=sys.stderr)
            print("Refine with --label, use the node id, or pass --all-matches.",
                  file=sys.stderr)
            return 1
        targets.extend(matches if args.all_matches else matches[:1])

    result = ImpactAnalyzer(graph).analyze(
        targets, depth=args.depth, direction=args.direction,
        include_rels=set(args.include_rel) if args.include_rel else None,
        exclude_rels=set(args.exclude_rel) if args.exclude_rel else None)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(impact_markdown(result))

    if args.save:
        base = Path(args.save)
        _write(base.with_suffix('.md'), impact_markdown(result))
        _write(base.with_suffix('.json'), json.dumps(result, indent=2))
        _write(base.with_suffix('.mmd'), impact_mermaid(result))
    if args.fail_on in ('CRITICAL', 'HIGH', 'MEDIUM'):
        order = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
        if order.index(result['summary']['riskBand']) >= order.index(args.fail_on):
            return 2
    return 0


def cmd_diagrams(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    graph = _load_graph(output_dir)
    target_dir = Path(args.diagram_dir) if args.diagram_dir else output_dir / 'generated_diagrams'

    produced: Dict[str, str] = {}
    if args.format in ('mermaid', 'both'):
        produced.update(mermaid.generate_all(graph))
    if args.format in ('plantuml', 'both'):
        produced.update(plantuml.generate_all(graph))

    for rel, content in produced.items():
        _write(target_dir / rel, content)
    _write(target_dir / 'README.md', _diagram_readme(produced, graph))
    print(f"\n{len(produced)} diagram sources written to {target_dir}")
    return 0


def _diagram_readme(produced: Dict[str, str], graph: Graph) -> str:
    lines = ['# Generated Diagrams', '',
             'Regenerate with `tibco-analyze diagrams --format both`. Every element is',
             'derived from the parsed knowledge graph — no assumed components.', '',
             f"Source graph: {len(graph.nodes)} nodes / {len(graph.rels)} relationships.",
             '', '| File | Type |', '|------|------|']
    for rel in sorted(produced):
        kind = 'Mermaid' if rel.endswith(('.mmd', '.md')) else 'PlantUML'
        lines.append(f'| `{rel}` | {kind} |')
    lines += ['', '## Rendering', '',
              '- **Mermaid:** renders natively in GitHub, VS Code (Markdown Preview '
              'Mermaid Support), or https://mermaid.live',
              '- **PlantUML:** `plantuml -tsvg <file>.puml`, or the VS Code PlantUML '
              'extension. No remote includes are used, so an offline server works.']
    return '\n'.join(lines) + '\n'


def cmd_context(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    graph = _load_graph(output_dir)
    written = ContextPackBuilder(graph, output_dir / 'context').build_all()
    print(f"\n{len(written)} context packs written to {output_dir / 'context'}")
    for name in sorted(written):
        print(f"  {name}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    graph = _load_graph(output_dir)
    reports_dir = Path(args.reports_dir) if args.reports_dir else output_dir / 'reports'
    inv = full_inventory(graph)
    written = generate_reports(graph, reports_dir, inv)
    _write(reports_dir / 'inventory.json', json.dumps(inv, indent=2, default=str))
    print(f"\nReports scaffolded in {reports_dir}:")
    for name in written:
        print(f"  {name}")
    print("\nSections marked `<!-- LLM: ... -->` are for Copilot to complete.")
    return 0


def cmd_queries(args: argparse.Namespace) -> int:
    output_dir = Path(args.output)
    _write(output_dir / 'analysis_queries.cypher', render_cookbook())
    _write(output_dir / 'ANALYSIS_QUERIES.md', queries_markdown())
    print(queries_markdown() if args.print_queries else
          f"Cookbook written to {output_dir}")
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    args.running_all = True
    rc = cmd_analyze(args)
    if rc:
        return rc
    validate_rc = cmd_validate(args)
    args.provider = getattr(args, 'provider', 'auto')
    args.no_embeddings = getattr(args, 'no_embeddings', False)
    cmd_index(args)
    args.format = getattr(args, 'format', 'both')
    args.diagram_dir = getattr(args, 'diagram_dir', None)
    cmd_diagrams(args)
    cmd_context(args)
    args.reports_dir = getattr(args, 'reports_dir', None)
    cmd_report(args)
    print('\nPipeline complete. Open the reports, then run the Copilot prompt '
          '`/tibco-bootstrap-analysis` (or the per-step prompts) to write the narrative sections.')
    return validate_rc


# ──────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='tibco-analyze',
        description='Deterministic TIBCO BusinessWorks analysis: knowledge graph, '
                    'semantic search, blast radius, diagrams and LLM context packs.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    parser.add_argument('--output', '-o', default=DEFAULT_OUTPUT,
                        help=f'Analysis output directory (default: {DEFAULT_OUTPUT})')
    parser.add_argument('--verbose', '-v', action='store_true')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('analyze', help='Parse the TIBCO project into a knowledge graph')
    p.add_argument('--source', '-s', required=True, help='TIBCO project root directory')
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser('validate', help='Validate graph integrity (CI gate)')
    p.add_argument('--strict', action='store_true', help='Treat warnings as failures')
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser('index', help='Build the semantic search index')
    p.add_argument('--source', '-s', help='TIBCO root (defaults to the analysed root)')
    p.add_argument('--no-embeddings', action='store_true',
                   help='Lexical-only index (no model, no network)')
    p.add_argument('--provider', default='auto',
                   choices=['auto', 'sentence-transformers', 'openai', 'azure-openai'])
    p.set_defaults(func=cmd_index)

    p = sub.add_parser('search', help='Find where functionality is implemented')
    p.add_argument('query', help='Natural-language question or keywords')
    p.add_argument('--top', '-k', type=int, default=10)
    p.add_argument('--label', '-l', action='append',
                   help='Restrict to a node label (repeatable)')
    p.add_argument('--module', '-m', action='append',
                   help='Restrict to a module (repeatable)')
    p.add_argument('--provider', default='auto',
                   choices=['auto', 'sentence-transformers', 'openai', 'azure-openai'])
    p.add_argument('--json', action='store_true')
    p.add_argument('--save', help='Also write the Markdown result to this path')
    p.set_defaults(func=cmd_search)

    p = sub.add_parser('impact', help='Blast radius of changing an artefact')
    p.add_argument('--target', '-t', action='append', required=True,
                   help='Node id, name, `Label:Name`, or file path (repeatable)')
    p.add_argument('--label', '-l', action='append', help='Disambiguate by label')
    p.add_argument('--depth', '-d', type=int, default=4)
    p.add_argument('--direction', default='upstream',
                   choices=['upstream', 'downstream', 'both'],
                   help='upstream = who depends on it (default); '
                        'downstream = what it depends on')
    p.add_argument('--include-rel', action='append', help='Only traverse these edge types')
    p.add_argument('--exclude-rel', action='append', help='Never traverse these edge types')
    p.add_argument('--all-matches', action='store_true',
                   help='Use every artefact matching the target instead of failing on ambiguity')
    p.add_argument('--fail-on', default='NONE',
                   choices=['NONE', 'MEDIUM', 'HIGH', 'CRITICAL'],
                   help='Exit 2 when the risk band reaches this level (CI gate)')
    p.add_argument('--json', action='store_true')
    p.add_argument('--save', help='Write .md/.json/.mmd next to this path stem')
    p.set_defaults(func=cmd_impact)

    p = sub.add_parser('diagrams', help='Generate Mermaid / PlantUML diagram sources')
    p.add_argument('--format', default='both', choices=['mermaid', 'plantuml', 'both'])
    p.add_argument('--diagram-dir', help='Output directory (default: <output>/generated_diagrams)')
    p.set_defaults(func=cmd_diagrams)

    p = sub.add_parser('context', help='Write LLM grounding packs')
    p.set_defaults(func=cmd_context)

    p = sub.add_parser('report', help='Scaffold the Step00/01/02 reports')
    p.add_argument('--reports-dir', help='Output directory (default: <output>/reports)')
    p.set_defaults(func=cmd_report)

    p = sub.add_parser('queries', help='Emit the Cypher query cookbook')
    p.add_argument('--print-queries', action='store_true')
    p.set_defaults(func=cmd_queries)

    p = sub.add_parser('all', help='Run the whole pipeline')
    p.add_argument('--source', '-s', required=True)
    p.add_argument('--strict', action='store_true')
    p.add_argument('--no-embeddings', action='store_true')
    p.add_argument('--provider', default='auto',
                   choices=['auto', 'sentence-transformers', 'openai', 'azure-openai'])
    p.add_argument('--format', default='both', choices=['mermaid', 'plantuml', 'both'])
    p.add_argument('--diagram-dir')
    p.add_argument('--reports-dir')
    p.set_defaults(func=cmd_all)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
