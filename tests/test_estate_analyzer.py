"""Tests for the estate analyzer (docs/ESTATE_ANALYZER_SPEC.md section 10).

Run with `pytest tests`, or directly with
`python tests/test_estate_analyzer.py` (no pytest needed for the direct path).

The three analyzers run over their committed fixtures into a temporary
directory, and the wrapper federates the result. `tests/fixtures/estate` adds
what the join needs and nothing else: one BW6 module whose datasource is mapped
to `ORDER_APP`, one BW5 module whose datasource deliberately is not, a
deliberate near-miss table name, and a `SQLDirect` activity carrying no static
SQL. The expected outcome is written down in `expected_links.json` before the
matcher runs, so a matcher that becomes more eager fails a test rather than
quietly inflating coverage.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'tools'))

from analyzer_core.analysis.impact import ImpactAnalyzer            # noqa: E402
from analyzer_core.graph.exporters import Neo4jExporter             # noqa: E402
from analyzer_core.graph.validate import GraphValidator             # noqa: E402
from analyzer_core.model import Graph                               # noqa: E402
from apex_analyzer.analyzer import ApexAnalyzer                     # noqa: E402
from estate_analyzer.analysis.inventory import (contended_tables,   # noqa: E402
                                                full_inventory,
                                                issues_summary)
from estate_analyzer.analysis.rules_catalog import apply_rules      # noqa: E402
from estate_analyzer.analysis.sequence import sequence              # noqa: E402
from estate_analyzer.federate import (federate, load_estate_map,    # noqa: E402
                                      load_sources)
from estate_analyzer.graph.schema import (impact_config,            # noqa: E402
                                          neo4j_schema,
                                          validation_config)
from estate_analyzer.links import link_estates                      # noqa: E402
from oracle_analyzer.analyzer import OracleAnalyzer                 # noqa: E402
from tibco_analyzer.analyzer import TibcoAnalyzer                   # noqa: E402

FIXTURES = REPO_ROOT / 'tests' / 'fixtures'
ESTATE_FIXTURE = FIXTURES / 'estate'
ESTATE_MAP = ESTATE_FIXTURE / 'estate_map.json'
EXPECTED = json.loads((ESTATE_FIXTURE / 'expected_links.json').read_text(encoding='utf-8'))
OWNER = 'ORDER_APP'


# ── harness ───────────────────────────────────────────────────────────
def _build_estates(tmp: Path) -> dict:
    """Run the three analyzers, exactly as an operator would, and save."""
    dirs = {'tibco': tmp / 'tibco', 'apex': tmp / 'apex', 'oracle': tmp / 'oracle'}
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    TibcoAnalyzer(ESTATE_FIXTURE / 'tibco', dirs['tibco']).analyze() \
        .save(dirs['tibco'] / 'graph.json')
    ApexAnalyzer(FIXTURES / 'apex', dirs['apex'],
                 db_meta=FIXTURES / 'apex' / 'db_meta.json').analyze() \
        .save(dirs['apex'] / 'graph.json')
    OracleAnalyzer(FIXTURES / 'oracle', dirs['oracle'], default_owner=OWNER) \
        .analyze().save(dirs['oracle'] / 'graph.json')
    return dirs


def _federate(tmp: Path, allow_name_match: bool = False):
    dirs = _build_estates(tmp)
    graph, federation = federate(load_sources(dirs))
    links = link_estates(graph, federation, load_estate_map(ESTATE_MAP),
                         allow_name_match=allow_name_match)
    issue_count = apply_rules(graph, federation, links)
    graph.meta['coverage'].update(links['coverage'])
    graph.meta['links'] = {'linkCount': len(links['links']),
                           'suppressedCount': len(links['suppressed']),
                           'unboundCount': len(links['unbound']),
                           'estateMap': str(ESTATE_MAP),
                           'allowNameMatch': allow_name_match}
    graph.meta['issueCount'] = issue_count
    return graph, federation, links, dirs


def _link_set(rows):
    return {(row['fromName'], row['relType'], row['toName'], row['basis'])
            for row in rows}


def _expected_set(key):
    return {(row['from'], row['rel'], row['to'], row['basis'])
            for row in EXPECTED[key]}


def _rule_ids(graph: Graph):
    return {str(node.properties.get('ruleId')) for node in graph.by_label('Issue')}


# ── the exact half of the join ────────────────────────────────────────
def test_database_objects_merge_on_natural_key():
    """APEX and Oracle share `analyzer_core.ids`, so their view of one table
    is one node. This half of the join needs no heuristic at all."""
    with tempfile.TemporaryDirectory() as tmp:
        graph, _, _, _ = _federate(Path(tmp))

    orders = graph.nodes['db:ORDER_APP.ORDERS']
    assert orders.label == 'DbTable'
    assert orders.properties['merged'] is True
    assert orders.properties['estates'] == 'apex;oracle'
    assert 'Federated' in orders.properties['extraLabels']
    assert graph.meta['coverage']['mergedDbNodes'] == 24


def test_merge_conflicts_are_resolved_by_dictionary_authority():
    """Where two estates disagree, the one with a data-dictionary extract wins
    -- and the loser is recorded rather than discarded silently."""
    with tempfile.TemporaryDirectory() as tmp:
        graph, federation, _, _ = _federate(Path(tmp))

    assert federation.authority['apex'] > federation.authority['oracle']
    conflicts = graph.meta['propertyConflicts']
    assert conflicts, 'the two fixtures do disagree; a run with no conflicts ' \
                      'means the arbitration stopped looking'
    assert all(c['resolvedBy'] == 'data-dictionary authority' for c in conflicts)
    # A locally-scoped metric is not a conflict: both estates measured their
    # own graph, so the breakdown is kept instead.
    assert not any(c['property'] in ('fanIn', 'origin') for c in conflicts)
    assert graph.nodes['db:ORDER_APP.ORDERS'].properties['fanInByEstate'] \
        == 'apex=3;oracle=4'


def test_estate_namespacing_prevents_collisions():
    """Every id except the `db:` family is namespaced, so two estates using
    `file:database/01_tables.sql` cannot become one node by accident."""
    with tempfile.TemporaryDirectory() as tmp:
        graph, _, _, _ = _federate(Path(tmp))

    for node_id, node in graph.nodes.items():
        if node_id.startswith('db:') or node.label == 'Estate' \
                or node_id.startswith('issue:'):
            continue
        assert node_id.split(':', 1)[0] in ('tibco', 'apex', 'oracle'), node_id
    assert 'apex:file:database/01_tables.sql' in graph.nodes
    assert 'oracle:file:schema/01_tables.sql' in graph.nodes


def test_content_addressed_nodes_are_not_merged():
    """`sql:`/`plsql:` ids are namespaced on purpose: merging them would hide
    the duplicate-logic finding that compares their digests."""
    with tempfile.TemporaryDirectory() as tmp:
        graph, _, _, _ = _federate(Path(tmp))

    content = [node for node in graph.nodes.values()
               if str(node.properties.get('sourceNodeId', '')).startswith(
                   ('sql:', 'plsql:'))]
    assert content
    assert not any(node.properties.get('merged') for node in content)


# ── the inferred half of the join ─────────────────────────────────────
def test_expected_links_are_produced():
    with tempfile.TemporaryDirectory() as tmp:
        _, _, links, _ = _federate(Path(tmp))

    assert _link_set(links['links']) == _expected_set('links')
    assert all(row['confidence'] > 0 for row in links['links'])
    assert all(row['evidence'] for row in links['links'])


def test_near_miss_table_is_not_matched():
    """ORDER_LINE is not ORDER_LINES. A matcher that normalises plurals, or
    falls back to a fuzzy match, fails here rather than in production."""
    with tempfile.TemporaryDirectory() as tmp:
        graph, _, links, _ = _federate(Path(tmp))

    unbound = {(row['activity'], row.get('table', ''), row['reason'])
               for row in links['unbound']}
    assert ('ReadNearMiss', 'ORDER_LINE', 'no-such-object') in unbound
    assert not any(row['fromName'] == 'ReadNearMiss' for row in links['links'])
    near_miss = next(node for node in graph.by_label('Activity')
                     if node.name == 'ReadNearMiss')
    assert not [rel for rel in graph.outgoing(near_miss.node_id)
                if rel.rel_type == 'READS_FROM']


def test_bare_name_match_is_suppressed_by_default():
    with tempfile.TemporaryDirectory() as tmp:
        _, _, links, _ = _federate(Path(tmp), allow_name_match=False)

    assert _link_set(links['suppressed']) == _expected_set('suppressedByDefault')
    assert not any(row['basis'] == 'name' for row in links['links'])


def test_bare_name_match_is_admitted_only_on_request():
    with tempfile.TemporaryDirectory() as tmp:
        _, _, links, _ = _federate(Path(tmp), allow_name_match=True)

    admitted = _link_set(links['links'])
    assert _expected_set('suppressedByDefault') <= admitted
    assert not links['suppressed']
    weak = [row for row in links['links'] if row['basis'] == 'name']
    assert all(row['confidence'] == 0.5 for row in weak)


def test_runtime_sql_is_reported_not_dropped():
    """A JDBC activity with no static SQL is a declared blind spot. It must be
    excluded from the coverage denominator and named in the unbound list."""
    with tempfile.TemporaryDirectory() as tmp:
        _, _, links, _ = _federate(Path(tmp))

    reasons = {row['activity']: row['reason'] for row in links['unbound']}
    assert reasons['DirectSql'] == 'no-static-sql'
    coverage = links['coverage']
    assert coverage['noStaticSqlSites'] == 1
    assert coverage['jdbcActivitiesWithSql'] == coverage['jdbcActivities'] - 1


def test_unmapped_datasource_is_reported():
    """A JDBC url names a database, not a schema. An unmapped resource must be
    reported, never guessed onto the schema that happens to be there."""
    with tempfile.TemporaryDirectory() as tmp:
        _, _, links, _ = _federate(Path(tmp))

    by_name = {row['name']: row for row in links['datasources']}
    for expected in EXPECTED['datasources']:
        assert by_name[expected['name']]['mapped'] == expected['mapped']
        assert by_name[expected['name']]['schema'] == expected['schema']


def test_coverage_matches_the_expected_figures():
    with tempfile.TemporaryDirectory() as tmp:
        _, _, links, _ = _federate(Path(tmp))

    for key, value in EXPECTED['coverage'].items():
        assert links['coverage'][key] == value, key


# ── findings ──────────────────────────────────────────────────────────
def test_rule_ids_are_namespaced_before_merging():
    """SEC-001 is SQL injection in APEX and unresolvable dynamic SQL in Oracle.
    Merged unprefixed, the ledger would be wrong rather than merely untidy."""
    with tempfile.TemporaryDirectory() as tmp:
        graph, _, _, _ = _federate(Path(tmp))

    rules = _rule_ids(graph)
    assert 'APEX.SEC-001' in rules
    assert 'ORA.SEC-001' in rules
    assert 'SEC-001' not in rules
    for issue in graph.by_label('Issue'):
        if issue.properties.get('estate') != 'cross':
            assert issue.properties['sourceRuleId']


def test_categories_are_canonicalised():
    """APEX spells it TECH_DEBT and Oracle spells it DEBT."""
    with tempfile.TemporaryDirectory() as tmp:
        graph, _, _, _ = _federate(Path(tmp))

    categories = {str(node.properties.get('category'))
                  for node in graph.by_label('Issue')}
    assert 'TECH_DEBT' not in categories
    assert 'DEBT' in categories
    debt = [node for node in graph.by_label('Issue')
            if node.properties.get('sourceCategory') == 'TECH_DEBT']
    assert debt, 'the APEX fixture does raise a TECH_DEBT finding'


def test_cross_estate_rules_fire_on_the_seeded_conditions():
    with tempfile.TemporaryDirectory() as tmp:
        graph, _, _, _ = _federate(Path(tmp))

    rules = _rule_ids(graph)
    for expected in EXPECTED['crossEstateRules']:
        assert expected in rules, expected
    for not_expected in EXPECTED['rulesThatMustNotFire']:
        assert not_expected not in rules, EXPECTED['rulesThatMustNotFire'][not_expected]


def test_contended_table_names_the_estates_that_write_it():
    with tempfile.TemporaryDirectory() as tmp:
        graph, _, _, _ = _federate(Path(tmp))

    contended = {row['name']: row for row in contended_tables(graph)}
    assert set(contended['AUDIT_LOG']['writerEstates']) == {'apex', 'oracle', 'tibco'}
    assert set(contended['ORDER_LINES']['writerEstates']) == {'apex', 'tibco'}


def test_every_finding_carries_a_recommendation():
    with tempfile.TemporaryDirectory() as tmp:
        graph, _, _, _ = _federate(Path(tmp))

    cross = [f for f in issues_summary(graph)['findings'] if f['estate'] == 'cross']
    assert cross
    assert all(f['recommendation'] for f in cross)


# ── gates ─────────────────────────────────────────────────────────────
def test_validation_reports_no_errors_and_the_right_warnings():
    """The fixture is deliberately below both coverage gates, because a
    near-miss table and an unmapped datasource are real conditions. The
    validator must warn, not pass silently and not fail."""
    with tempfile.TemporaryDirectory() as tmp:
        graph, _, _, _ = _federate(Path(tmp))
        result = GraphValidator(graph, validation_config(), Path(tmp)).run()

    assert result['errors'] == 0, [f for f in result['findings']
                                   if f['severity'] == 'ERROR']
    assert result['status'] == 'WARN'
    warned = {f['rule'] for f in result['findings'] if f['severity'] == 'WARNING'}
    assert warned == {'sql-bind-coverage', 'datasource-coverage'}
    infos = {f['rule'] for f in result['findings'] if f['severity'] == 'INFO'}
    assert {'cross-estate-links', 'merged-db-nodes', 'estate-provenance'} <= infos


def test_every_inferred_edge_carries_its_confidence():
    """AX-PROV in the core validator enforces this, and so does the design:
    an inferred edge without a confidence is indistinguishable from an
    extracted one. Edges the wrapper adds carry more -- the basis they rest on
    and the evidence for them -- because those are the ones a reviewer has to
    be able to reject."""
    with tempfile.TemporaryDirectory() as tmp:
        graph, _, _, _ = _federate(Path(tmp))

    inferred = [rel for rel in graph.rels
                if rel.properties.get('origin') in ('inferred', 'declared')]
    assert inferred
    assert all('confidence' in rel.properties for rel in inferred)

    added = [rel for rel in inferred
             if rel.properties.get('purpose') in ('cross-estate-data-access',
                                                  'datasource-mapping')]
    assert added
    for rel in added:
        assert rel.properties['basis'] in ('declared', 'qualified-name', 'name')
        assert rel.properties['evidence']
        assert 0 < rel.properties['confidence'] <= 1.0


def test_neo4j_export_round_trips():
    with tempfile.TemporaryDirectory() as tmp:
        graph, _, _, _ = _federate(Path(tmp))
        files = Neo4jExporter(graph, Path(tmp) / 'export', neo4j_schema()).write_all()
        # SQL and PL/SQL text carries newlines, so a row is not a line: parse
        # the export the way neo4j-admin import would.
        with open(files['nodes_csv'], newline='', encoding='utf-8') as handle:
            nodes = list(csv.DictReader(handle))
        with open(files['relationships_csv'], newline='', encoding='utf-8') as handle:
            rels = list(csv.DictReader(handle))

    by_id = {row['nodeId:ID']: row for row in nodes}
    assert len(by_id) == len(graph.nodes)
    labels = by_id['db:ORDER_APP.ORDERS']['label:LABEL'].split(';')
    assert labels[0] == 'DbTable'
    assert 'Federated' in labels, 'the merge must survive into the export'
    assert any(row['label:LABEL'] == 'Estate' for row in nodes)
    rel_types = {row[':TYPE'] for row in rels}
    assert {'CONNECTS_TO_SCHEMA', 'CONTAINS_ESTATE', 'INSERTS_INTO'} <= rel_types


# ── the questions the wrapper exists to answer ────────────────────────
def test_impact_crosses_estate_boundaries():
    """A change to a shared table reaches all three estates. No single-estate
    analysis would have shown that, which is the whole point."""
    with tempfile.TemporaryDirectory() as tmp:
        graph, _, _, _ = _federate(Path(tmp))

    target = graph.nodes['db:ORDER_APP.ORDER_LINES']
    result = ImpactAnalyzer(graph, impact_config()).analyze(
        [target], depth=6, direction='upstream')
    reached = {graph.nodes[row['nodeId']].properties.get('estate')
               for row in result['impacted']}
    assert {'tibco', 'apex'} <= reached
    assert result['summary']['affectedEntryPoints'] > 0


def test_sequence_puts_ownership_decisions_before_the_move():
    with tempfile.TemporaryDirectory() as tmp:
        graph, _, _, _ = _federate(Path(tmp))

    result = sequence(graph)
    waves = {wave['wave']: wave for wave in result['waves']}
    blockers = {item['subject'] for item in waves[0]['items']}
    assert {'AUDIT_LOG', 'ORDER_LINES'} <= blockers
    assert 'LegacyFeed' in blockers          # the unmapped datasource
    assert 'DirectSql' in blockers           # the runtime-SQL blind spot

    groups = {group['table'] for group in waves[1]['items']}
    assert {'AUDIT_LOG', 'ORDER_LINES'} <= groups
    audit = next(g for g in waves[1]['items'] if g['table'] == 'AUDIT_LOG')
    assert {member['estate'] for member in audit['components']} == \
        {'apex', 'oracle', 'tibco'}


def test_inventory_is_complete():
    with tempfile.TemporaryDirectory() as tmp:
        graph, _, _, _ = _federate(Path(tmp))
        inventory = full_inventory(graph)

    assert set(inventory) == {'summary', 'estates', 'coverage', 'links',
                              'tableAccess', 'contendedTables',
                              'boundaryComponents', 'hotspots', 'issues'}
    assert inventory['summary']['estates'] == 3
    assert inventory['summary']['contendedTables'] == 3
    assert len(inventory['estates']) == 3


# ── the architectural promises ────────────────────────────────────────
def test_wrapper_imports_no_analyzer():
    """The wrapper reads finished graphs, and only finished graphs. Importing
    an analyzer would couple it to a parser and break the rule in AGENTS.md."""
    package = REPO_ROOT / 'tools' / 'estate_analyzer'
    offenders = []
    for path in sorted(package.rglob('*.py')):
        text = path.read_text(encoding='utf-8')
        for analyzer in ('tibco_analyzer', 'apex_analyzer', 'oracle_analyzer'):
            if f'import {analyzer}' in text or f'from {analyzer}' in text:
                offenders.append(f'{path.name} imports {analyzer}')
    assert not offenders, offenders


def test_federation_does_not_touch_the_upstream_outputs():
    """`federate` is read-only. An estate's output directory must be
    byte-identical after a federation run."""
    with tempfile.TemporaryDirectory() as tmp:
        dirs = _build_estates(Path(tmp))
        before = {estate: hashlib.sha256(
            (path / 'graph.json').read_bytes()).hexdigest()
            for estate, path in dirs.items()}

        graph, federation = federate(load_sources(dirs))
        links = link_estates(graph, federation, load_estate_map(ESTATE_MAP))
        apply_rules(graph, federation, links)

        after = {estate: hashlib.sha256(
            (path / 'graph.json').read_bytes()).hexdigest()
            for estate, path in dirs.items()}
        assert before == after
        assert sorted(p.name for p in dirs['tibco'].iterdir()) == ['graph.json']


def test_a_missing_estate_is_an_error_not_a_silent_two_estate_graph():
    with tempfile.TemporaryDirectory() as tmp:
        dirs = _build_estates(Path(tmp))
        dirs['oracle'] = Path(tmp) / 'not-analysed'
        try:
            load_sources(dirs)
        except FileNotFoundError as exc:
            assert 'oracle' in str(exc)
        else:                                          # pragma: no cover
            raise AssertionError('a missing estate must not be skipped quietly')


def test_graph_round_trips_through_json():
    with tempfile.TemporaryDirectory() as tmp:
        graph, _, _, _ = _federate(Path(tmp))
        path = Path(tmp) / 'federated.json'
        graph.save(path)
        reloaded = Graph.load(path)

    assert len(reloaded.nodes) == len(graph.nodes)
    assert len(reloaded.rels) == len(graph.rels)
    assert reloaded.meta['schemaVersion'] == 'estate-1.0.0'
    assert reloaded.nodes['db:ORDER_APP.ORDERS'].properties['estates'] == 'apex;oracle'


if __name__ == '__main__':
    failures = 0
    for name, function in sorted(globals().items()):
        if not name.startswith('test_') or not callable(function):
            continue
        try:
            function()
            print(f'PASS  {name}')
        except AssertionError as exc:
            failures += 1
            print(f'FAIL  {name}: {exc}')
        except Exception as exc:                       # noqa: BLE001
            failures += 1
            print(f'ERROR {name}: {type(exc).__name__}: {exc}')
    print(f'\n{failures} failure(s)')
    sys.exit(1 if failures else 0)
