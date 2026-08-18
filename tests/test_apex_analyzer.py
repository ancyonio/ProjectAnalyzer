"""Tests for the APEX analyzer.

Run with `pytest tests`, or directly with `python tests/test_apex_analyzer.py`
(no pytest needed for the direct path).

The fixture under `tests/fixtures/apex` is a small APEX split export plus its
schema DDL, carrying deliberately seeded defects — dynamic SQL built by
concatenation, `WHEN OTHERS THEN NULL`, `SELECT *`, an unrestricted public
page, an unused LOV — so the rule catalogue has something to find.
"""
from __future__ import annotations

import csv
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'tools'))

from analyzer_core.graph.exporters import Neo4jExporter          # noqa: E402
from analyzer_core.graph.validate import GraphValidator          # noqa: E402
from analyzer_core.model import Graph                            # noqa: E402
from apex_analyzer.analysis.inventory import full_inventory      # noqa: E402
from apex_analyzer.analyzer import ApexAnalyzer                  # noqa: E402
from apex_analyzer.graph.schema import neo4j_schema, validation_config  # noqa: E402

FIXTURE = REPO_ROOT / 'tests' / 'fixtures' / 'apex'


def _analyze(tmp: Path, **kwargs) -> Graph:
    return ApexAnalyzer(FIXTURE, tmp, **kwargs).analyze()


def _rule_ids(graph: Graph):
    return {node.properties.get('ruleId') for node in graph.by_label('Issue')}


# ── structure ─────────────────────────────────────────────────────────
def test_components_are_extracted():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    assert len(graph.by_label('ApexApplication')) == 1
    assert {p.properties['pageId'] for p in graph.by_label('ApexPage')} == {1, 10, 20}
    assert len(graph.by_label('ApexRegion')) == 6
    assert len(graph.by_label('ApexItem')) == 6
    assert len(graph.by_label('ApexButton')) == 4
    assert len(graph.by_label('ApexProcess')) == 4          # 3 page + 1 application
    assert len(graph.by_label('ApexValidation')) == 1
    assert len(graph.by_label('ApexBranch')) == 1
    assert len(graph.by_label('ApexDynamicAction')) == 1
    assert len(graph.by_label('ApexDaAction')) == 2
    assert len(graph.by_label('ApexLov')) == 3
    assert len(graph.by_label('ApexAuthorization')) == 2
    assert graph.meta['unhandledProcedures'] == {}, 'an export call was not handled'


def test_database_layer_from_ddl():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    tables = {t.name for t in graph.by_label('DbTable')}
    assert {'ORDERS', 'ORDER_LINES', 'CUSTOMERS'} <= tables
    units = {u.name for u in graph.by_label('DbProgramUnit')}
    assert {'ORDER_PKG.SAVE_ORDER', 'ORDER_PKG.CREATE_ORDER',
            'ORDER_PKG.ORDER_TOTAL'} <= units
    assert len(graph.by_label('DbView')) == 1
    assert any(c.properties.get('isPk') for c in graph.by_label('DbColumn'))


def test_data_access_edges():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    orders = next(t for t in graph.by_label('DbTable') if t.name == 'ORDERS')
    incoming = {rel.rel_type for rel in graph.incoming(orders.node_id)}
    assert 'READS_FROM' in incoming
    assert 'WRITES_TO' in incoming and 'UPDATES' in incoming
    assert all('confidence' in rel.properties
               for rel in graph.incoming(orders.node_id)
               if rel.rel_type in ('READS_FROM', 'WRITES_TO', 'UPDATES'))


def test_button_triggers_process_and_binds_items():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    save = next(b for b in graph.by_label('ApexButton') if b.name == 'SAVE')
    triggered = [graph.node(r.end_id).name for r in graph.outgoing(save.node_id)
                 if r.rel_type == 'TRIGGERS']
    assert 'Save Order' in triggered

    order_id = next(i for i in graph.by_label('ApexItem')
                    if i.properties.get('itemName') == 'P10_ORDER_ID')
    binders = [r for r in graph.incoming(order_id.node_id) if r.rel_type == 'BINDS_ITEM']
    assert binders, 'no code binds :P10_ORDER_ID'


def test_column_lineage_for_a_form_page():
    """A form region has no SQL; lineage must still reach the column."""
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    customer_item = next(i for i in graph.by_label('ApexItem')
                         if i.properties.get('itemName') == 'P10_CUSTOMER_ID')
    columns = [graph.node(r.end_id) for r in graph.outgoing(customer_item.node_id)
               if r.rel_type == 'REFERENCES_COLUMN']
    assert [c.name for c in columns] == ['CUSTOMER_ID']
    assert columns[0].properties['tableName'] == 'ORDERS'


def test_package_membership_is_not_a_call_path():
    """Calling one unit of a package must not make the whole package reachable.

    ORDER_PKG.ARCHIVE_ORDERS writes to ORDERS_ARCHIVE and nothing in the
    application calls it; a page that calls ORDER_PKG.SAVE_ORDER must not
    therefore appear to write to ORDERS_ARCHIVE.
    """
    from apex_analyzer.analysis.inventory import dead_code               # noqa: PLC0415
    from apex_analyzer.analysis.traverse import descend                  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp), db_meta=FIXTURE / 'db_meta.json')

    page_10 = next(p for p in graph.by_label('ApexPage')
                   if p.properties['pageId'] == 10)
    reached = {graph.node(n).name for n in descend(graph, page_10.node_id, max_depth=8)
               if graph.node(n) is not None}
    assert 'ORDERS' in reached
    assert 'ORDERS_ARCHIVE' not in reached, 'HAS_UNIT was traversed as a call path'

    unreached = {u['name'] for u in dead_code(graph)['programUnitsNotReached']}
    assert 'ORDER_PKG.ARCHIVE_ORDERS' in unreached
    # …but a unit called from an application process or an authorization scheme
    # is reached, even though no page contains its caller
    assert 'ORDER_PKG.IS_ORDER_CLERK' not in unreached
    assert 'ORDER_PKG.DEFAULT_CUSTOMER' not in unreached


def test_navigation_graph():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    page_20 = next(p for p in graph.by_label('ApexPage')
                   if p.properties['pageId'] == 20)
    inbound = {rel.rel_type for rel in graph.incoming(page_20.node_id)}
    assert 'NAVIGATES_TO' in inbound


# ── rules ─────────────────────────────────────────────────────────────
def test_rules_fire_on_seeded_defects():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))
    found = _rule_ids(graph)

    for rule in ('SEC-001',       # dynamic SQL by concatenation
                 'SEC-003',       # unrestricted page with unprotected items
                 'SEC-004',       # public page querying application data
                 'CORR-001',      # reference to ORDERS_ARCHIVE, absent from the DDL
                 'CORR-003',      # WHEN OTHERS THEN NULL
                 'CORR-004',      # COMMIT in a page process
                 'PERF-001',      # SELECT * in a region source
                 'PERF-002',      # per-row LOV in a report column
                 'PERF-005',      # hardcoded hint
                 'SEC-007',       # &ITEM. substitution instead of a bind
                 'DEBT-002',      # unused LOV
                 'DEBT-003'):     # component disabled by a build option
        assert rule in found, f'{rule} did not fire'

    # negative: nothing should be flagged as an unreachable page here
    assert 'DEBT-001' not in found

    for issue in graph.by_label('Issue'):
        assert issue.properties.get('evidence'), 'a finding cites no evidence'
        recommendations = [r for r in graph.outgoing(issue.node_id)
                           if r.rel_type == 'HAS_RECOMMENDATION']
        assert recommendations, 'a finding carries no recommendation'


# ── graph quality ─────────────────────────────────────────────────────
def test_validation_passes():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))
        result = GraphValidator(graph, validation_config()).run()
    assert result['status'] in ('PASS', 'WARN'), result['findings']
    assert result['errors'] == 0, [f for f in result['findings']
                                   if f['severity'] == 'ERROR']


def test_resolution_coverage_is_reported_and_high():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))
    coverage = graph.meta['coverage']
    assert coverage['totalResolutions'] > 0
    assert coverage['resolutionCoverage'] >= 0.80, coverage
    assert 'ORDER_APP.ORDERS_ARCHIVE' in coverage['unresolvedNames']


def test_analysis_is_deterministic():
    with tempfile.TemporaryDirectory() as tmp:
        first = _analyze(Path(tmp) / 'a').to_dict()
        second = _analyze(Path(tmp) / 'b').to_dict()
    first['meta'].pop('generatedAt')
    second['meta'].pop('generatedAt')
    assert json.dumps(first, sort_keys=True, default=str) == \
        json.dumps(second, sort_keys=True, default=str)


def test_neo4j_export_round_trips():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        graph = _analyze(out)
        graph.save(out / 'graph.json')
        files = Neo4jExporter(graph, out, neo4j_schema()).write_all()

        # SQL text carries newlines, so the CSV must be read as CSV, not lines
        with open(files['nodes_csv'], newline='', encoding='utf-8') as handle:
            node_rows = list(csv.DictReader(handle))
        with open(files['relationships_csv'], newline='', encoding='utf-8') as handle:
            rel_rows = list(csv.DictReader(handle))
        assert len(node_rows) == len(graph.nodes)
        assert len(rel_rows) == len(graph.rels)
        assert {row['nodeId:ID'] for row in node_rows} == set(graph.nodes)

        sidecar = json.loads(Path(files['index_sidecar']).read_text(encoding='utf-8'))
        assert sidecar['fulltextIndexes'], 'no full-text index declared'
        assert any(entry['label'] == 'ApexPage'
                   for entry in sidecar['compositeConstraints'])
        # multi-label nodes must survive the CSV round trip
        assert any(';DbObject' in row['label:LABEL'] for row in node_rows)


# ── dictionary extract ────────────────────────────────────────────────
def test_dictionary_extract_adds_facts_ddl_cannot():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp), db_meta=FIXTURE / 'db_meta.json')

    orders = next(t for t in graph.by_label('DbTable') if t.name == 'ORDERS')
    assert orders.properties['numRows'] == 1450000
    assert any(s.name == 'ORDERS_SYN' for s in graph.by_label('DbSynonym'))
    # ORDERS_ARCHIVE is in the dictionary but not the DDL, so it now resolves
    assert any(t.name == 'ORDERS_ARCHIVE' for t in graph.by_label('DbTable'))
    assert 'PERF-003' in _rule_ids(graph), 'large-table report rule needs row counts'


def test_inventory_is_complete():
    with tempfile.TemporaryDirectory() as tmp:
        inventory = full_inventory(_analyze(Path(tmp)))
    assert inventory['summary']['pages'] == 3
    assert inventory['issues']['total'] > 0
    assert inventory['dataAccess'], 'no data access rows'
    assert inventory['security']['unsecuredPages'], 'page 20 has no authorization'
    assert inventory['businessFunctions'], 'no business function seed'


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
