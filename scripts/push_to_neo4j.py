#!/usr/bin/env python3
"""Push the analyzer's Neo4j artefacts into a running Neo4j database.

The deterministic pipeline writes three Neo4j-relevant files into the analysis
output directory:

    neo4j_nodes.csv           typed node table  (nodeId:ID, label:LABEL, ...)
    neo4j_relationships.csv   edge table        (:START_ID, :END_ID, :TYPE, ...)
    neo4j_import.cypher       a standalone CREATE script for cypher-shell

This script loads the two CSVs over the Bolt driver in batched UNWIND
transactions, which is far faster than replaying the .cypher script statement
by statement and preserves the typed columns (`:int`, `:float`, `:boolean`).

    # settings from .env (copy .env.example and fill it in)
    python scripts/push_to_neo4j.py

    # explicit, wiping the database first
    python scripts/push_to_neo4j.py -o analysis_output --uri bolt://localhost:7687 \
        --user neo4j --password secret --wipe --yes

    # no Python driver installed? replay the generated script through cypher-shell
    python scripts/push_to_neo4j.py --via-cypher-shell

Connection settings resolve in this order, first hit wins:

    command-line flag  >  environment variable  >  .env file  >  built-in default

so an exported NEO4J_PASSWORD in CI overrides a developer's .env rather than the
other way round. The .env is looked for in the working directory and then at the
repository root; `--env-file` points elsewhere and `--no-env-file` skips it.

    NEO4J_URI  NEO4J_USERNAME  NEO4J_PASSWORD  NEO4J_DATABASE

Loading is idempotent: nodes MERGE on `nodeId`, relationships MERGE on
(start, end, type), so re-running against an already-loaded database updates
properties in place rather than duplicating the graph.

Requires `pip install "neo4j>=5.0"` (declared as the `neo4j` extra in
pyproject.toml) and a Neo4j 5.x server for the constraint/index syntax.
"""
from __future__ import annotations

import argparse
import csv
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = 'analysis_output'

NODES_CSV = 'neo4j_nodes.csv'
RELS_CSV = 'neo4j_relationships.csv'
CYPHER_SCRIPT = 'neo4j_import.cypher'

ENV_FILE = '.env'
ENV_KEY = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

# Labels and relationship types are interpolated into Cypher (the driver cannot
# parameterise them), so every one is checked against this before use.
IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

INDEX_SIDECAR = 'neo4j_indexes.json'

# Fallback for an analysis output written before the exporter emitted
# `neo4j_indexes.json`: the TIBCO analyzer's secondary indexes.
SECONDARY_INDEXES: List[Tuple[str, str]] = [
    ('BWProcess', 'module'),
    ('BWProcess', 'tier'),
    ('Activity', 'category'),
    ('XSD', 'namespace'),
    ('SharedResource', 'resourceType'),
    ('GlobalVariable', 'module'),
]


def load_index_spec(out_dir: Path) -> Dict[str, Any]:
    """Read the exporter's index sidecar, so one push script serves every
    dialect. Falls back to the built-in TIBCO list when it is absent."""
    path = out_dir / INDEX_SIDECAR
    if not path.is_file():
        return {
            'indexes': [{'label': label, 'properties': [prop]}
                        for label, prop in SECONDARY_INDEXES],
            'compositeConstraints': [],
            'fulltextIndexes': [],
            'source': 'built-in fallback',
        }
    try:
        spec = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        print(f'  WARNING: cannot read {path.name} ({exc}); using the built-in '
              f'index list')
        return {'indexes': [], 'compositeConstraints': [], 'fulltextIndexes': [],
                'source': 'unreadable sidecar'}
    spec['source'] = path.name
    return spec


# --------------------------------------------------------------------------
# .env loading
#
# Deliberately hand-rolled rather than depending on python-dotenv: the toolkit
# declares zero required runtime dependencies so it runs on an air-gapped agent.
# --------------------------------------------------------------------------

def parse_dotenv(text: str) -> Dict[str, str]:
    """Parse `KEY=value` lines. Supports `export ` prefixes, quoted values and
    `#` comments; a `#` inside a quoted value is kept, so passwords survive."""
    values: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        key, sep, value = line.partition('=')
        key = key.strip()
        if not sep or not ENV_KEY.match(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            quote, value = value[0], value[1:-1]
            if quote == '"':
                value = value.replace('\\n', '\n').replace('\\"', '"')
        else:
            comment = value.find(' #')
            if comment != -1:
                value = value[:comment].rstrip()
        values[key] = value
    return values


def find_env_file(explicit: str = None) -> Path:
    """`--env-file` wins; otherwise ./.env, otherwise <repo root>/.env."""
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise SystemExit(f"ERROR: --env-file not found: {path}")
        return path
    for candidate in (Path.cwd() / ENV_FILE, REPO_ROOT / ENV_FILE):
        if candidate.is_file():
            return candidate
    return None


def load_dotenv(explicit: str = None) -> Path:
    """Populate os.environ from a .env file without clobbering real env vars,
    so an explicitly exported NEO4J_PASSWORD still wins in CI."""
    path = find_env_file(explicit)
    if path is None:
        return None
    try:
        text = path.read_text(encoding='utf-8-sig')
    except OSError as exc:
        raise SystemExit(f"ERROR: cannot read {path}: {exc}")
    for key, value in parse_dotenv(text).items():
        os.environ.setdefault(key, value)
    return path


# --------------------------------------------------------------------------
# CSV reading
# --------------------------------------------------------------------------

def _coerce(value: str, kind: str) -> Any:
    """Turn a CSV cell into the type its `name:type` header declared."""
    if kind == 'int':
        return int(float(value))
    if kind == 'float':
        return float(value)
    if kind == 'boolean':
        return value.strip().lower() in ('true', '1', 'yes')
    return value


def _split_header(column: str) -> Tuple[str, str]:
    """`activityCount:int` -> ('activityCount', 'int'); `name` -> ('name', '')."""
    if ':' in column:
        head, _, kind = column.rpartition(':')
        return head, kind
    return column, ''


def read_nodes(path: Path) -> Tuple[Dict[str, List[dict]], int]:
    """Group node rows by label. Returns (rows_by_label, total_rows)."""
    by_label: Dict[str, List[dict]] = defaultdict(list)
    total = 0
    with open(path, newline='', encoding='utf-8') as fh:
        reader = csv.reader(fh)
        header = next(reader)
        parsed = [_split_header(c) for c in header]
        try:
            id_idx = next(i for i, (_, k) in enumerate(parsed) if k == 'ID')
            label_idx = next(i for i, (_, k) in enumerate(parsed) if k == 'LABEL')
        except StopIteration:
            raise SystemExit(f"ERROR: {path.name} has no ':ID' and ':LABEL' columns")

        for row in reader:
            if not row or not row[id_idx]:
                continue
            total += 1
            props: dict = {'nodeId': row[id_idx]}
            for i, cell in enumerate(row):
                if i in (id_idx, label_idx) or cell == '':
                    continue
                key, kind = parsed[i]
                try:
                    props[key] = _coerce(cell, kind)
                except ValueError:
                    props[key] = cell  # keep the raw text rather than drop the fact
            # admin-import allows `A;B` for multi-label nodes
            for label in row[label_idx].split(';'):
                label = label.strip()
                if label:
                    by_label[label].append(props)
    return by_label, total


def read_relationships(path: Path) -> Tuple[Dict[str, List[dict]], int]:
    """Group edge rows by type. Returns (rows_by_type, total_rows)."""
    by_type: Dict[str, List[dict]] = defaultdict(list)
    total = 0
    with open(path, newline='', encoding='utf-8') as fh:
        reader = csv.reader(fh)
        header = next(reader)
        parsed = [_split_header(c) for c in header]
        try:
            start_idx = next(i for i, (_, k) in enumerate(parsed) if k == 'START_ID')
            end_idx = next(i for i, (_, k) in enumerate(parsed) if k == 'END_ID')
            type_idx = next(i for i, (_, k) in enumerate(parsed) if k == 'TYPE')
        except StopIteration:
            raise SystemExit(
                f"ERROR: {path.name} has no ':START_ID'/':END_ID'/':TYPE' columns")

        for row in reader:
            if not row or not row[type_idx]:
                continue
            total += 1
            props: dict = {}
            for i, cell in enumerate(row):
                if i in (start_idx, end_idx, type_idx) or cell == '':
                    continue
                key, kind = parsed[i]
                try:
                    props[key] = _coerce(cell, kind)
                except ValueError:
                    props[key] = cell
            by_type[row[type_idx]].append({
                'start': row[start_idx],
                'end': row[end_idx],
                'props': props,
            })
    return by_type, total


def check_identifiers(names, what: str) -> None:
    bad = [n for n in names if not IDENTIFIER.match(n)]
    if bad:
        raise SystemExit(
            f"ERROR: refusing to build Cypher from unsafe {what}: {', '.join(sorted(bad))}"
        )


def report_parallel_edges(by_type: Dict[str, List[dict]]) -> None:
    """MERGE collapses parallel same-type edges; say so if any exist."""
    counts = Counter(
        (r['start'], r['end'], rtype)
        for rtype, rows in by_type.items()
        for r in rows
    )
    dupes = sum(v - 1 for v in counts.values() if v > 1)
    if dupes:
        print(f"  WARNING: {dupes} parallel same-type edge(s) will be collapsed by MERGE "
              f"(properties of the last one win)")


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def batched(rows: List[dict], size: int):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def wipe(session, batch: int) -> None:
    print('  Wiping existing graph ...')
    # Autocommit: CALL {} IN TRANSACTIONS is illegal inside an explicit transaction.
    session.run(
        f'MATCH (n) CALL {{ WITH n DETACH DELETE n }} IN TRANSACTIONS OF {batch} ROWS'
    ).consume()


def create_schema(session, labels: List[str], spec: Dict[str, Any]) -> None:
    print(f"  Constraints and indexes (from {spec.get('source', 'defaults')}) ...")
    present = set(labels)
    for label in labels:
        session.run(
            f'CREATE CONSTRAINT IF NOT EXISTS FOR (n:`{label}`) REQUIRE n.nodeId IS UNIQUE'
        ).consume()
        session.run(
            f'CREATE INDEX IF NOT EXISTS FOR (n:`{label}`) ON (n.name)'
        ).consume()

    for entry in spec.get('compositeConstraints', []) or []:
        label, properties = entry.get('label'), entry.get('properties') or []
        if label not in present or not properties:
            continue
        check_identifiers([label] + properties, 'constraint identifiers')
        keys = ', '.join(f'n.`{prop}`' for prop in properties)
        session.run(f'CREATE CONSTRAINT IF NOT EXISTS FOR (n:`{label}`) '
                    f'REQUIRE ({keys}) IS UNIQUE').consume()

    for entry in spec.get('indexes', []) or []:
        label, properties = entry.get('label'), entry.get('properties') or []
        if label not in present or not properties:
            continue
        check_identifiers([label] + properties, 'index identifiers')
        keys = ', '.join(f'n.`{prop}`' for prop in properties)
        session.run(f'CREATE INDEX IF NOT EXISTS FOR (n:`{label}`) ON ({keys})').consume()

    for entry in spec.get('fulltextIndexes', []) or []:
        name = entry.get('name')
        usable = [lbl for lbl in entry.get('labels') or [] if lbl in present]
        properties = entry.get('properties') or []
        if not name or not usable or not properties:
            continue
        check_identifiers([name] + usable + properties, 'full-text identifiers')
        label_expr = '|'.join(f'`{lbl}`' for lbl in usable)
        prop_expr = ', '.join(f'n.`{prop}`' for prop in properties)
        session.run(f'CREATE FULLTEXT INDEX {name} IF NOT EXISTS '
                    f'FOR (n:{label_expr}) ON EACH [{prop_expr}]').consume()


def delete_dataset(session, dataset_id: str, batch: int) -> int:
    """Remove one dataset (one application, one extract) without touching the
    rest of the graph — the reload path for a multi-application database."""
    print(f"  Removing existing dataset '{dataset_id}' ...")
    result = session.run(
        'MATCH (n {datasetId: $dataset}) '
        'CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF ' + str(batch) + ' ROWS',
        dataset=dataset_id)
    summary = result.consume()
    removed = summary.counters.nodes_deleted
    print(f'    {removed} node(s) deleted')
    return removed


def load_nodes(session, by_label: Dict[str, List[dict]], batch: int) -> int:
    written = 0
    for label in sorted(by_label):
        rows = by_label[label]
        query = (
            'UNWIND $rows AS row '
            f'MERGE (n:`{label}` {{nodeId: row.nodeId}}) '
            'SET n += row'
        )
        for chunk in batched(rows, batch):
            session.execute_write(lambda tx, c=chunk: tx.run(query, rows=c).consume())
        written += len(rows)
        print(f"    {label:<18} {len(rows):>6} nodes")
    return written


def load_relationships(session, by_type: Dict[str, List[dict]], batch: int) -> int:
    written = 0
    skipped = 0
    for rtype in sorted(by_type):
        rows = by_type[rtype]
        query = (
            'UNWIND $rows AS row '
            'MATCH (a {nodeId: row.start}) '
            'MATCH (b {nodeId: row.end}) '
            f'MERGE (a)-[e:`{rtype}`]->(b) '
            'SET e += row.props '
            'RETURN count(e) AS created'
        )
        made = 0
        for chunk in batched(rows, batch):
            made += session.execute_write(
                lambda tx, c=chunk: tx.run(query, rows=c).single()['created']
            )
        skipped += len(rows) - made
        written += made
        note = f"  ({len(rows) - made} skipped: endpoint missing)" if made < len(rows) else ''
        print(f"    {rtype:<24} {made:>6} rels{note}")
    if skipped:
        print(f"  WARNING: {skipped} relationship(s) skipped because an endpoint node "
              f"was not found - check that both CSVs come from the same analysis run")
    return written


def verify(session, expected_nodes: int, expected_rels: int) -> bool:
    n = session.run('MATCH (n) RETURN count(n) AS c').single()['c']
    r = session.run('MATCH ()-[e]->() RETURN count(e) AS c').single()['c']
    print(f"\n  Verify: {n} nodes in database (CSV had {expected_nodes})")
    print(f"  Verify: {r} relationships in database (CSV had {expected_rels})")
    ok = n >= expected_nodes and r >= expected_rels
    if not ok:
        print('  WARNING: database holds fewer entities than the CSVs describe')
    return ok


# --------------------------------------------------------------------------
# cypher-shell fallback
# --------------------------------------------------------------------------

def via_cypher_shell(script: Path, uri: str, user: str, password: str,
                     database: str, dry_run: bool) -> int:
    exe = shutil.which('cypher-shell')
    if not exe:
        print('ERROR: cypher-shell not found on PATH. Install the Neo4j client tools, '
              'or use the default driver mode with `pip install "neo4j>=5.0"`.',
              file=sys.stderr)
        return 1
    cmd = [exe, '-a', uri, '-u', user, '-p', password, '-d', database,
           '--format', 'plain', '-f', str(script)]
    shown = list(cmd)
    shown[shown.index(password)] = '***'
    print('  ' + ' '.join(shown))
    if dry_run:
        print('  (dry run - not executed)')
        return 0
    return subprocess.call(cmd)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument('--output', '-o', default=DEFAULT_OUTPUT,
                   help=f'Analysis output directory holding the neo4j_* files '
                        f'(default: {DEFAULT_OUTPUT})')
    p.add_argument('--env-file',
                   help=f'Config file to read connection settings from '
                        f'(default: ./{ENV_FILE}, then <repo root>/{ENV_FILE})')
    p.add_argument('--no-env-file', action='store_true',
                   help=f'Ignore {ENV_FILE} and use only the environment and flags')
    p.add_argument('--uri', default=os.environ.get('NEO4J_URI', 'bolt://localhost:7687'),
                   help='Bolt URI (env: NEO4J_URI, default: bolt://localhost:7687)')
    p.add_argument('--user', '-u',
                   default=os.environ.get('NEO4J_USERNAME')
                           or os.environ.get('NEO4J_USER', 'neo4j'),
                   help='Username (env: NEO4J_USERNAME, default: neo4j)')
    p.add_argument('--password', '-p', default=os.environ.get('NEO4J_PASSWORD'),
                   help='Password (env: NEO4J_PASSWORD; prompted for if omitted)')
    p.add_argument('--database', '-d', default=os.environ.get('NEO4J_DATABASE', 'neo4j'),
                   help='Target database (env: NEO4J_DATABASE, default: neo4j)')
    p.add_argument('--wipe', action='store_true',
                   help='DETACH DELETE every node before loading')
    p.add_argument('--dataset',
                   help='Delete only the nodes carrying this datasetId before '
                        'loading, leaving other applications and the shared '
                        'database layer intact (see the APEX spec, reload '
                        'semantics). Use instead of --wipe on a shared database.')
    p.add_argument('--yes', '-y', action='store_true',
                   help='Do not prompt for confirmation before --wipe')
    p.add_argument('--batch-size', type=int, default=1000,
                   help='Rows per write transaction (default: 1000)')
    p.add_argument('--no-indexes', action='store_true',
                   help='Skip constraint and index creation')
    p.add_argument('--dry-run', action='store_true',
                   help='Parse and report what would be pushed, without connecting')
    p.add_argument('--via-cypher-shell', action='store_true',
                   help=f'Replay {CYPHER_SCRIPT} through cypher-shell instead of '
                        f'loading the CSVs over Bolt')
    return p.parse_args(argv)


def main(argv=None) -> int:
    # The .env has to land in os.environ before parse_args(), because the
    # connection flags take their defaults from os.environ at parse time.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument('--env-file')
    pre.add_argument('--no-env-file', action='store_true')
    known, _ = pre.parse_known_args(argv)
    env_path = None if known.no_env_file else load_dotenv(known.env_file)

    args = parse_args(argv)

    out_dir = Path(args.output)
    if not out_dir.is_absolute():
        candidate = REPO_ROOT / out_dir
        out_dir = candidate if candidate.exists() else out_dir.resolve()
    if not out_dir.is_dir():
        print(f"ERROR: analysis output directory not found: {out_dir}\n"
              f"       Run: PYTHONPATH=tools python -m tibco_analyzer -o {args.output} "
              f"analyze --source <tibco_root>", file=sys.stderr)
        return 1

    print(f"Config: {env_path}" if env_path else
          f"Config: no {ENV_FILE} found (using environment and flags)")
    print(f"Source: {out_dir}")
    print(f"Target: {args.uri}  database={args.database}  user={args.user}\n")

    # ---- cypher-shell path ------------------------------------------------
    if args.via_cypher_shell:
        script = out_dir / CYPHER_SCRIPT
        if not script.is_file():
            print(f"ERROR: {script} not found", file=sys.stderr)
            return 1
        password = args.password or getpass.getpass(f'Password for {args.user}: ')
        return via_cypher_shell(script, args.uri, args.user, password,
                                args.database, args.dry_run)

    # ---- read and validate the CSVs --------------------------------------
    nodes_path, rels_path = out_dir / NODES_CSV, out_dir / RELS_CSV
    missing = [p.name for p in (nodes_path, rels_path) if not p.is_file()]
    if missing:
        print(f"ERROR: missing in {out_dir}: {', '.join(missing)}\n"
              f"       Run the analyze step to regenerate them.", file=sys.stderr)
        return 1

    index_spec = load_index_spec(out_dir)
    nodes_by_label, node_total = read_nodes(nodes_path)
    rels_by_type, rel_total = read_relationships(rels_path)
    labels = sorted(nodes_by_label)
    rel_types = sorted(rels_by_type)
    check_identifiers(labels, 'node labels')
    check_identifiers(rel_types, 'relationship types')

    print(f"Parsed {node_total} nodes across {len(labels)} labels, "
          f"{rel_total} relationships across {len(rel_types)} types")
    report_parallel_edges(rels_by_type)

    if args.dry_run:
        print('\nWould load:')
        for label in labels:
            print(f"    {label:<18} {len(nodes_by_label[label]):>6} nodes")
        for rtype in rel_types:
            print(f"    {rtype:<24} {len(rels_by_type[rtype]):>6} rels")
        print('\n(dry run - nothing was written)')
        return 0

    try:
        from neo4j import GraphDatabase
        from neo4j.exceptions import AuthError, ServiceUnavailable
    except ImportError:
        print('ERROR: the Neo4j Python driver is not installed.\n'
              '       pip install "neo4j>=5.0"        (or: pip install -e ".[neo4j]")\n'
              '       Alternatively run with --via-cypher-shell.', file=sys.stderr)
        return 1

    password = args.password or getpass.getpass(f'Password for {args.user}: ')

    if args.dataset and args.wipe:
        print('ERROR: use either --wipe or --dataset, not both.', file=sys.stderr)
        return 1

    if args.wipe and not args.yes:
        answer = input(f"Delete ALL nodes and relationships in '{args.database}' "
                       f"at {args.uri}? [y/N] ").strip().lower()
        if answer not in ('y', 'yes'):
            print('Aborted.')
            return 1

    driver = GraphDatabase.driver(args.uri, auth=(args.user, password))
    try:
        driver.verify_connectivity()
    except AuthError:
        driver.close()
        print(f"ERROR: authentication failed for user '{args.user}'", file=sys.stderr)
        return 1
    except ServiceUnavailable as exc:
        driver.close()
        print(f"ERROR: cannot reach Neo4j at {args.uri} - {exc}", file=sys.stderr)
        return 1

    try:
        with driver.session(database=args.database) as session:
            print('\nPushing:')
            if args.wipe:
                wipe(session, args.batch_size)
            elif args.dataset:
                delete_dataset(session, args.dataset, args.batch_size)
            if not args.no_indexes:
                create_schema(session, labels, index_spec)
            print('  Nodes ...')
            written_nodes = load_nodes(session, nodes_by_label, args.batch_size)
            print('  Relationships ...')
            written_rels = load_relationships(session, rels_by_type, args.batch_size)
            ok = verify(session, node_total, rel_total)
    finally:
        driver.close()

    print(f"\nDone: {written_nodes} nodes, {written_rels} relationships pushed to "
          f"{args.uri}/{args.database}")
    return 0 if ok else 2


if __name__ == '__main__':
    sys.exit(main())
