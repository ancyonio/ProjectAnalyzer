"""Tests for the Oracle analyzer (docs/ORACLE_ANALYZER_SPEC.md §10).

Run with `pytest tests`, or directly with `python tests/test_oracle_analyzer.py`
(no pytest needed for the direct path).

The fixture under `tests/fixtures/oracle` is a small Oracle estate carrying
deliberately seeded conditions, so the analyzer's boundaries are asserted
rather than assumed: an overloaded function, dynamic SQL built by
concatenation, a call to a package that is not in the tree, a private unit
nothing calls, and a credential in a deployment script.
"""
from __future__ import annotations

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
from oracle_analyzer.analysis.inventory import full_inventory       # noqa: E402
from oracle_analyzer.analysis.lineage import lineage                # noqa: E402
from oracle_analyzer.analyzer import OracleAnalyzer                 # noqa: E402
from oracle_analyzer.graph.schema import (impact_config,            # noqa: E402
                                          neo4j_schema,
                                          validation_config)

FIXTURE = REPO_ROOT / 'tests' / 'fixtures' / 'oracle'
OWNER = 'ORDER_APP'


def _analyze(tmp: Path, **kwargs) -> Graph:
    return OracleAnalyzer(FIXTURE, tmp, default_owner=OWNER, **kwargs).analyze()


def _named(graph: Graph, label: str):
    return {node.name: node for node in graph.by_label(label)}


def _ids(graph: Graph, label: str):
    return {node.node_id for node in graph.by_label(label)}


def _rel_pairs(graph: Graph, rel_type: str):
    return {(graph.nodes[r.start_id].name, graph.nodes[r.end_id].name)
            for r in graph.rels if r.rel_type == rel_type
            and r.start_id in graph.nodes and r.end_id in graph.nodes}


def _rule_ids(graph: Graph):
    return {node.properties.get('ruleId') for node in graph.by_label('Issue')}


# ── schema layer ──────────────────────────────────────────────────────
def test_schema_objects_are_extracted():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    assert set(_named(graph, 'DbTable')) == {
        'CUSTOMERS', 'ORDERS', 'ORDER_LINES', 'AUDIT_LOG', 'ORDERS_ARCHIVE'}
    assert set(_named(graph, 'DbView')) == {'OPEN_ORDERS_V'}
    assert set(_named(graph, 'DbSequence')) == {'ORDER_SEQ'}
    assert set(_named(graph, 'DbSynonym')) == {'CUST'}
    assert set(_named(graph, 'DbTrigger')) == {'ORDERS_AUDIT_TRG'}
    assert len(graph.by_label('DbIndex')) == 1
    assert set(_named(graph, 'DbSchema')) == {OWNER}


def test_columns_and_keys():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    customers = _named(graph, 'DbTable')['CUSTOMERS']
    columns = {graph.nodes[r.end_id].name
               for r in graph.outgoing(customers.node_id)
               if r.rel_type == 'HAS_COLUMN'}
    assert columns == {'CUSTOMER_ID', 'NAME', 'REGION_CODE', 'CREATED_ON'}
    assert customers.properties['columnCount'] == 4


def test_foreign_keys_become_dependencies():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    depends = _rel_pairs(graph, 'DEPENDS_ON')
    assert ('ORDERS', 'CUSTOMERS') in depends
    assert ('ORDER_LINES', 'ORDERS') in depends


def test_view_lineage_and_synonym_resolution():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    depends = _rel_pairs(graph, 'DEPENDS_ON')
    assert ('OPEN_ORDERS_V', 'ORDERS') in depends
    assert ('OPEN_ORDERS_V', 'CUSTOMERS') in depends
    assert ('CUST', 'CUSTOMERS') in _rel_pairs(graph, 'RESOLVES_TO')


def test_trigger_fires_on_its_table():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    assert ('ORDERS_AUDIT_TRG', 'ORDERS') in _rel_pairs(graph, 'FIRES_ON')


# ── program structure ─────────────────────────────────────────────────
def test_packages_split_into_spec_and_body():
    """A spec change breaks callers; a body change does not. The graph has to
    be able to tell them apart."""
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    assert set(_named(graph, 'DbPackage')) == {'CUSTOMER_PKG', 'AUDIT_PKG'}
    assert f'db:{OWNER}.CUSTOMER_PKG#spec' in _ids(graph, 'PackageSpec')
    assert f'db:{OWNER}.CUSTOMER_PKG#body' in _ids(graph, 'PackageBody')
    assert ('CUSTOMER_PKG', 'CUSTOMER_PKG') in _rel_pairs(graph, 'HAS_SPEC')
    assert ('CUSTOMER_PKG', 'CUSTOMER_PKG') in _rel_pairs(graph, 'HAS_BODY')


def test_overloads_are_distinct_units():
    """GET_CUSTOMER is declared twice. Collapsing overloads would silently
    merge two different subprograms into one node."""
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    units = _ids(graph, 'DbProgramUnit')
    assert f'db:{OWNER}.CUSTOMER_PKG.GET_CUSTOMER' in units
    assert f'db:{OWNER}.CUSTOMER_PKG.GET_CUSTOMER#2' in units


def test_published_units_are_entry_points_even_when_implemented():
    """The body pass must not un-publish what the spec published -- including
    when the body file sorts before the spec file, as `.pkb` does."""
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    published = {n.name for n in graph.by_label('DbProgramUnit')
                 if n.properties.get('isPublished')}
    assert {'CREATE_CUSTOMER', 'DELETE_CUSTOMER', 'GET_CUSTOMER',
            'LOG_ACTION', 'PURGE_OLD_LOGS'} <= published
    assert 'UNUSED_HELPER' not in published


def test_parameterless_declaration_is_recognised():
    """`PROCEDURE PURGE_OLD_LOGS;` has no argument list and was invisible."""
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    spec = f'db:{OWNER}.AUDIT_PKG#spec'
    declared = {graph.nodes[r.end_id].name for r in graph.outgoing(spec)
                if r.rel_type == 'HAS_UNIT'}
    assert declared == {'LOG_ACTION', 'PURGE_OLD_LOGS'}


def test_standalone_units_belong_to_the_schema():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    units = _named(graph, 'DbProgramUnit')
    assert units['ARCHIVE_ORDERS'].properties['isStandalone'] is True
    assert units['ORDER_TOTAL'].properties['unitType'] == 'FUNCTION'
    assert units['ARCHIVE_ORDERS'].properties['packageName'] == ''


# ── data access ───────────────────────────────────────────────────────
def test_data_access_uses_the_specific_verb_and_the_rollup():
    """WRITES_TO alone cannot separate an insert from a delete, and that
    distinction is what a lineage or retention question turns on."""
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    assert ('CUSTOMERS' in {t for _, t in _rel_pairs(graph, 'INSERTS_INTO')})
    assert ('CUSTOMERS' in {t for _, t in _rel_pairs(graph, 'DELETES_FROM')})
    assert ('CUSTOMERS' in {t for _, t in _rel_pairs(graph, 'READS_FROM')})
    # every specific write verb also carries the roll-up
    written = {t for _, t in _rel_pairs(graph, 'WRITES_TO')}
    assert {'CUSTOMERS', 'AUDIT_LOG', 'ORDERS_ARCHIVE'} <= written


def test_insert_select_records_both_sides():
    """`INSERT INTO archive SELECT ... FROM orders` writes one table and reads
    another; recording only the write loses half the lineage."""
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    for statement in graph.by_label('SqlStatement'):
        if statement.properties.get('verb') != 'INSERT':
            continue
        targets = {(r.rel_type, graph.nodes[r.end_id].name)
                   for r in graph.outgoing(statement.node_id)
                   if r.end_id in graph.nodes}
        if ('INSERTS_INTO', 'ORDERS_ARCHIVE') in targets:
            assert ('READS_FROM', 'ORDERS') in targets
            return
    raise AssertionError('the INSERT ... SELECT statement was not found')


def test_call_graph_resolves_within_and_across_packages():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    calls = _rel_pairs(graph, 'CALLS')
    assert ('CREATE_CUSTOMER', 'LOG_ACTION') in calls
    assert ('ORDERS_AUDIT_TRG', 'LOG_ACTION') in calls


def test_a_units_own_header_is_not_a_call_to_itself():
    """`CREATE PROCEDURE ORDER_APP.ARCHIVE_ORDERS` is schema-qualified. Read as
    a package-qualified call it made every standalone unit reference itself
    and fail to resolve."""
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    unresolved = {n.name for n in graph.by_label('UnresolvedRef')}
    assert f'{OWNER}.ARCHIVE_ORDERS' not in unresolved
    assert f'{OWNER}.ORDER_TOTAL' not in unresolved


def test_sequence_usage_is_recorded():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))
    assert ('CREATE_CUSTOMER', 'ORDER_SEQ') in _rel_pairs(graph, 'USES_SEQUENCE')


# ── the honesty contract (spec §7) ────────────────────────────────────
def test_dynamic_sql_is_declared_not_guessed():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    archive = _named(graph, 'DbProgramUnit')['ARCHIVE_ORDERS']
    assert archive.properties['hasDynamicSql'] is True
    assert graph.meta['coverage']['dynamicSqlSites'] == 1
    assert 'SEC-001' in _rule_ids(graph)


def test_an_unresolvable_call_is_recorded_not_dropped():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    assert 'LEGACY_UTIL.CLEANUP' in {n.name for n in graph.by_label('UnresolvedRef')}
    assert graph.meta['coverage']['callsUnresolved'] == 1


def test_coverage_is_reported_and_below_100():
    """The fixture seeds one unresolvable call on purpose: a coverage figure
    that can only ever read 100% is not measuring anything."""
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    coverage = graph.meta['coverage']
    assert coverage['dictionaryAvailable'] is False
    assert 0 < coverage['callResolution'] < 100
    assert coverage['resolutionCoverage'] < 100


def test_credentials_never_enter_the_graph():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    serialised = json.dumps(graph.to_dict())
    assert 'hunter2-not-a-real-password' not in serialised


# ── rules ─────────────────────────────────────────────────────────────
def test_rules_fire_on_seeded_defects():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    fired = _rule_ids(graph)
    assert 'SEC-001' in fired, 'dynamic SQL'
    assert 'CORR-001' in fired, 'WHEN OTHERS THEN NULL'
    assert 'CORR-003' in fired, 'DELETE with no WHERE'
    assert 'PERF-002' in fired, 'optimizer hint'
    assert 'DEBT-002' in fired, 'uncalled private unit'
    assert 'DEBT-004' in fired, 'unresolved reference'


def test_dead_code_does_not_flag_published_units():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    flagged = {issue.properties.get('targetName')
               for issue in graph.by_label('Issue')
               if issue.properties.get('ruleId') == 'DEBT-002'}
    assert flagged == {'UNUSED_HELPER'}


def test_findings_carry_a_source_location():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    for issue in graph.by_label('Issue'):
        if issue.properties.get('ruleId') == 'DEBT-004':
            continue      # an unresolved reference has no file by definition
        assert issue.properties.get('filePath'), \
            f"{issue.properties.get('ruleId')} has no source location"


# ── analysis surface ──────────────────────────────────────────────────
def test_inventory_is_complete():
    with tempfile.TemporaryDirectory() as tmp:
        inventory = full_inventory(_analyze(Path(tmp)))

    assert inventory['summary']['tables'] == 5
    assert inventory['summary']['packages'] == 2
    assert inventory['summary']['programUnits'] == 9
    assert inventory['schemas'][0]['name'] == OWNER
    assert inventory['entryPoints'], 'no entry points'
    assert inventory['dataAccess'], 'no data access rows'
    assert inventory['hotspots'][0]['name'] == 'CUSTOMERS'


def test_lineage_reports_both_directions():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    result = lineage(graph, _named(graph, 'DbTable')['CUSTOMERS'])
    assert {row['unit'] for row in result['upstream']} == {
        'CREATE_CUSTOMER', 'DELETE_CUSTOMER'}
    assert 'GET_CUSTOMER' in {row['unit'] for row in result['downstream']}
    assert result['views'] == ['OPEN_ORDERS_V']


def test_blast_radius_reaches_callers_of_a_table():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    target = _named(graph, 'DbTable')['CUSTOMERS']
    result = ImpactAnalyzer(graph, impact_config()).analyze(
        [target], direction='upstream')
    reached = {row['name'] for row in result['impacted']}
    assert 'CREATE_CUSTOMER' in reached
    assert 'OPEN_ORDERS_V' in reached


def test_package_membership_is_not_a_call_path():
    """Calling one unit must not make every other unit in the package -- and
    everything they touch -- look reachable."""
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    target = _named(graph, 'DbProgramUnit')['LOG_ACTION']
    result = ImpactAnalyzer(graph, impact_config()).analyze(
        [target], direction='upstream')
    reached = {row['name'] for row in result['impacted']}
    assert 'PURGE_OLD_LOGS' not in reached


# ── graph integrity ───────────────────────────────────────────────────
def test_validation_passes():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        graph = _analyze(tmp_path)
        Neo4jExporter(graph, tmp_path, neo4j_schema()).write_all()
        result = GraphValidator(graph, validation_config(), tmp_path).run()

    assert result['status'] == 'PASS', [f for f in result['findings']
                                        if f['severity'] != 'INFO']


def test_analysis_is_deterministic():
    with tempfile.TemporaryDirectory() as tmp:
        first = _analyze(Path(tmp)).to_dict()
    with tempfile.TemporaryDirectory() as tmp:
        second = _analyze(Path(tmp)).to_dict()

    for snapshot in (first, second):
        snapshot['meta'].pop('generatedAt', None)
        snapshot['meta'].pop('sourceRoot', None)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_neo4j_export_round_trips():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        graph = _analyze(tmp_path)
        Neo4jExporter(graph, tmp_path, neo4j_schema()).write_all()
        nodes_csv = (tmp_path / 'neo4j_nodes.csv').read_text(encoding='utf-8')
        rels_csv = (tmp_path / 'neo4j_relationships.csv').read_text(encoding='utf-8')

    assert len(nodes_csv.strip().splitlines()) >= len(graph.nodes)
    assert 'CUSTOMER_PKG' in nodes_csv
    assert 'INSERTS_INTO' in rels_csv
    assert 'WRITES_TO' in rels_csv


def test_deployment_scripts_are_not_analysed():
    """`install.sql` is plumbing, and the credential it holds must not reach
    the graph through it."""
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    files = {node.properties.get('filePath') for node in graph.by_label('File')}
    assert not any(str(path).startswith('deploy/') for path in files if path)


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
