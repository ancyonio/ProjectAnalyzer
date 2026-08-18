"""Tests for the TIBCO analyzer.

Run with `pytest tests`, or directly with `python tests/test_tibco_analyzer.py`
(no pytest needed for the direct path).

The fixture under `tests/fixtures/tibco` carries one module of each generation,
because the two are structurally unrelated and a parser that handles one can
silently drop the other:

- `DemoModuleBW5` -- a BW5 `.process` plus a `.sharedjdbc` shared resource,
  which names its resource inline.
- `DemoModuleBW6` -- two BW6 `.bwp` processes plus `.jdbcResource`,
  `.jmsConnResource` and `.smtpResource`. BW6 binds resources indirectly through
  a process property carrying `sca-bpel:sharedResourceType`, and one of the two
  processes calls the other through an activity that carries no
  `activityTypeID` at all.

Both resource files carry an obfuscated password so the graph can be asserted
never to contain one.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'tools'))

from tibco_analyzer.analysis.impact import ImpactAnalyzer           # noqa: E402
from tibco_analyzer.analysis.inventory import (entry_points,        # noqa: E402
                                               full_inventory,
                                               integration_surface)
from tibco_analyzer.analyzer import TibcoAnalyzer                   # noqa: E402
from tibco_analyzer.constants import bw6_activity_mapping           # noqa: E402
from tibco_analyzer.graph.exporters import Neo4jExporter            # noqa: E402
from tibco_analyzer.graph.validate import GraphValidator            # noqa: E402
from tibco_analyzer.model import Graph                              # noqa: E402

FIXTURE = REPO_ROOT / 'tests' / 'fixtures' / 'tibco'


def _analyze(tmp: Path) -> Graph:
    return TibcoAnalyzer(FIXTURE, tmp).analyze()


def _named(graph: Graph, label: str):
    return {node.name: node for node in graph.by_label(label)}


def _rel_pairs(graph: Graph, rel_type: str):
    return {(graph.nodes[r.start_id].name, graph.nodes[r.end_id].name)
            for r in graph.rels if r.rel_type == rel_type
            and r.start_id in graph.nodes and r.end_id in graph.nodes}


# ── both generations parse ────────────────────────────────────────────
def test_both_process_generations_are_parsed():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    processes = _named(graph, 'BWProcess')
    assert set(processes) == {'ArchiveOrders', 'OrderIntake', 'OrderDispatcher'}
    assert processes['ArchiveOrders'].properties['bwVersion'] == 'BW5'
    assert processes['OrderIntake'].properties['bwVersion'] == 'BW6'
    assert processes['OrderDispatcher'].properties['bwVersion'] == 'BW6'


def test_modules_and_schemas_are_parsed():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    assert set(_named(graph, 'Module')) == {'DemoModuleBW5', 'DemoModuleBW6'}
    assert len(graph.by_label('XSD')) == 1
    assert {'Order', 'OrderAck'} <= set(_named(graph, 'Element'))
    assert ('OrderIntake', 'Order') in _rel_pairs(graph, 'USES_XSD')


# ── shared resources: the BW6 regression this suite exists for ────────
def test_shared_resources_are_parsed_in_both_generations():
    """BW6 resources are named `.jdbcResource`, not `.sharedjdbc`.

    Keying the parser on the BW5 spellings alone dropped every BW6 resource
    silently, which emptied the integration surface without failing anything.
    """
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    resources = _named(graph, 'SharedResource')
    assert set(resources) == {
        'LegacyOrdersDB',                 # BW5  .sharedjdbc
        'Demo_JDBCConnectionResource',    # BW6  .jdbcResource
        'Demo_JMSConnectionResource',     # BW6  .jmsConnResource
        'Demo_SMTPResource',              # BW6  .smtpResource
    }
    assert resources['LegacyOrdersDB'].properties['bwVersion'] == 'BW5'
    assert resources['Demo_JDBCConnectionResource'].properties['bwVersion'] == 'BW6'


def test_shared_resource_types_are_classified():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    types = {name: node.properties['resourceType']
             for name, node in _named(graph, 'SharedResource').items()}
    assert types == {
        'LegacyOrdersDB': 'JDBC_CONNECTION',
        'Demo_JDBCConnectionResource': 'JDBC_CONNECTION',
        'Demo_JMSConnectionResource': 'JMS_CONNECTION',
        'Demo_SMTPResource': 'SMTP',
    }


def test_bw6_resource_detail_is_read_from_attributes():
    """BW5 keeps detail in child elements, BW6 in attributes."""
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    resources = _named(graph, 'SharedResource')

    jdbc = resources['Demo_JDBCConnectionResource'].properties
    assert jdbc['url'] == 'jdbc:oracle:thin:@orders-db.internal:1521/ORDERS'
    assert jdbc['driver'] == 'oracle.jdbc.OracleDriver'
    assert jdbc['qualifiedName'] == 'demo.Demo_JDBCConnectionResource'

    jms = resources['Demo_JMSConnectionResource'].properties
    assert jms['url'] == 'tcp://ems.internal:7222'

    smtp = resources['Demo_SMTPResource'].properties
    assert (smtp['host'], smtp['port']) == ('smtp.internal', '25')

    legacy = resources['LegacyOrdersDB'].properties
    assert legacy['host'] == 'legacy-db.internal'
    assert legacy['driver'] == 'oracle.jdbc.OracleDriver'


def test_processes_reference_the_resources_they_use():
    """BW6 binds a resource through a process property, not by file name."""
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    assert _rel_pairs(graph, 'REFERENCES') == {
        ('ArchiveOrders', 'LegacyOrdersDB'),
        ('OrderIntake', 'Demo_JDBCConnectionResource'),
        ('OrderIntake', 'Demo_JMSConnectionResource'),
    }


def test_resources_connect_to_external_systems():
    """The documented model traverses SharedResource -> System directly."""
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    connects = {src for src, _ in _rel_pairs(graph, 'CONNECTS_TO')}
    assert {'Demo_JDBCConnectionResource', 'Demo_JMSConnectionResource',
            'LegacyOrdersDB'} <= connects
    assert {'JDBC_System', 'JMS_System'} <= set(_named(graph, 'System'))
    assert graph.by_label('Adapter'), 'no adapter nodes'


def test_credentials_never_enter_the_graph():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    serialised = json.dumps(graph.to_dict())
    for secret in ('OBFUSCATEDPASSWORD', 'orders_app', 'legacy_app',
                   's3cr3t-should-not-appear'):
        assert secret not in serialised, f'{secret!r} leaked into the graph'

    gvars = _named(graph, 'GlobalVariable')
    assert gvars['OrderDbPassword'].properties['value'] == '***MASKED***'
    assert gvars['OrderQueueName'].properties['value'] == 'ORDERS.INBOUND'


# ── activity classification and entry points ──────────────────────────
def test_entry_points_are_detected_in_both_generations():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    kinds = {node.name: node.properties['entryType']
             for node in graph.by_label('BWProcess')}
    assert kinds == {'ArchiveOrders': 'TIMER',
                     'OrderIntake': 'JMS_RECEIVER',
                     'OrderDispatcher': 'TIMER'}
    assert len(entry_points(graph)) == 3


def test_bw6_activities_are_named_and_classified():
    """A `receiveEvent` is an activity too; unnamed ones used to become
    `Activity_N` and lose their type."""
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    activities = {node.name: node.properties['category']
                  for node in graph.by_label('Activity')}
    assert activities == {
        'TimerStart': 'TIMER',
        'ArchiveQuery': 'JDBC_QUERY',
        'WriteArchiveFile': 'FILE_WRITE',
        'JMSReceiveOrder': 'JMS_RECEIVER',
        'JDBCQuery': 'JDBC_QUERY',
        'JMSSend': 'JMS_SEND',
        'DispatchTimer': 'TIMER',
        'OrderIntakeCallProcess': 'CALL_PROCESS',
    }


def test_a_subprocess_call_is_classified_even_without_a_type_id():
    """Some BW6 call-process activities carry no `activityTypeID`. Naming a
    target process is evidence enough -- otherwise a dozen subprocess calls read
    as unclassified custom work needing a manual rewrite."""
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    caller = _named(graph, 'Activity')['OrderIntakeCallProcess']
    assert caller.properties['category'] == 'CALL_PROCESS'
    assert caller.properties['rawType'] == '', 'fixture no longer covers the no-type case'
    assert ('OrderIntakeCallProcess', 'OrderIntake') in _rel_pairs(graph, 'CALLS')


def test_a_jms_receive_is_not_classified_as_a_send():
    """BW6 emits `bw.jms.receive`; the plugin-family fallback defaults to
    JMS_SEND, which silently turned every consumer into a producer."""
    assert bw6_activity_mapping('bw.jms.receive')['category'] == 'JMS_RECEIVER'
    assert bw6_activity_mapping('bw.jms.send')['category'] == 'JMS_SEND'
    assert bw6_activity_mapping('bw.http.HTTPReceiver')['category'] == 'HTTP_RECEIVER'
    # An uncatalogued inbound plugin activity must not read as outbound either.
    assert bw6_activity_mapping('bw.jms.receiveSomethingNew')['category'] == 'JMS_RECEIVER'
    # ...while a genuinely outbound one keeps its family default.
    assert bw6_activity_mapping('bw.jms.sendSomethingNew')['category'] == 'JMS_SEND'


def test_control_flow_is_connected():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    transitions = _rel_pairs(graph, 'TRANSITIONS_TO')
    assert ('JMSReceiveOrder', 'JDBCQuery') in transitions
    assert ('JDBCQuery', 'JMSSend') in transitions
    assert ('TimerStart', 'ArchiveQuery') in transitions


# ── graph integrity ───────────────────────────────────────────────────
def test_validation_passes():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        graph = _analyze(tmp_path)
        Neo4jExporter(graph, tmp_path).write_all()
        result = GraphValidator(graph, tmp_path).run()

    # Errors are the gate. The fixture is deliberately small, so it carries no
    # subprocess calls or fault handlers and the relationship-coverage rule
    # warns about their absence -- that warning is the rule working, not a
    # defect, so it is named here rather than silently tolerated.
    assert result['errors'] == 0, result['findings']
    warned = {f['rule'] for f in result['findings'] if f['severity'] == 'WARNING'}
    assert warned <= {'relationship-coverage'}, result['findings']


def test_coverage_is_reported():
    """An analyst cannot tell a small estate from a partly-parsed one without
    this, so it is a published fact rather than a log line."""
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    coverage = graph.meta['coverage']
    assert coverage['filesDiscovered'] == coverage['filesModelled']
    assert coverage['artifactCoverage'] == 100.0
    assert coverage['estateFileCoverage'] == 100.0
    assert coverage['unmodelledExtensions'] == {}
    assert coverage['unmodelledSupportedExtensions'] == {}


def test_unmodelled_java_does_not_report_a_parser_gap():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / 'source'
        shutil.copytree(FIXTURE, source)
        (source / 'DemoModuleBW6' / 'Helper.java').write_text(
            'final class Helper {}\n', encoding='utf-8')

        graph = TibcoAnalyzer(source, tmp_path / 'output').analyze()
        result = GraphValidator(graph).run()

    coverage = graph.meta['coverage']
    assert coverage['artifactCoverage'] == 100.0
    assert coverage['estateFileCoverage'] < 100.0
    assert coverage['unmodelledExtensions'] == {'.java': 1}
    assert coverage['unmodelledSupportedExtensions'] == {}
    warnings = {f['rule'] for f in result['findings']
                if f['severity'] == 'WARNING'}
    assert 'artifact-coverage' not in warnings


def test_shared_resource_coverage_rule_catches_a_parser_gap():
    """The rule that would have caught the BW6 gap: resource files on disk but
    no SharedResource nodes is an error, not a quiet warning."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        graph = _analyze(tmp_path)
        # Simulate a parser that discovered the files but modelled none.
        stripped = Graph({nid: n for nid, n in graph.nodes.items()
                          if n.label != 'SharedResource'},
                         [r for r in graph.rels],
                         dict(graph.meta))
        result = GraphValidator(stripped).run()

    gap = [f for f in result['findings'] if f['rule'] == 'shared-resource-coverage']
    assert gap and gap[0]['severity'] == 'ERROR', result['findings']


def test_analysis_is_deterministic():
    with tempfile.TemporaryDirectory() as tmp:
        first = _analyze(Path(tmp)).to_dict()
    with tempfile.TemporaryDirectory() as tmp:
        second = _analyze(Path(tmp)).to_dict()

    for snapshot in (first, second):
        snapshot['meta'].pop('generatedAt', None)
        snapshot['meta'].pop('tibcoRoot', None)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_neo4j_export_round_trips():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        graph = _analyze(tmp_path)
        Neo4jExporter(graph, tmp_path).write_all()

        nodes_csv = (tmp_path / 'neo4j_nodes.csv').read_text(encoding='utf-8')
        rels_csv = (tmp_path / 'neo4j_relationships.csv').read_text(encoding='utf-8')

    # One header row plus one row per node.
    assert len(nodes_csv.strip().splitlines()) >= len(graph.nodes)
    assert 'Demo_JDBCConnectionResource' in nodes_csv
    assert 'REFERENCES' in rels_csv


# ── analysis surface ──────────────────────────────────────────────────
def test_integration_surface_lists_the_external_systems():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    surface = integration_surface(graph)
    assert surface, 'integration surface is empty'
    categories = {row['category'] for row in surface}
    assert {'JDBC_QUERY', 'JMS_SEND', 'JMS_RECEIVER'} & categories


def test_blast_radius_reaches_the_processes_using_a_resource():
    with tempfile.TemporaryDirectory() as tmp:
        graph = _analyze(Path(tmp))

    target = _named(graph, 'SharedResource')['Demo_JDBCConnectionResource']
    result = ImpactAnalyzer(graph).analyze([target], direction='upstream')
    reached = {row['name'] for row in result['impacted']}
    assert 'OrderIntake' in reached, result['impacted']


def test_inventory_is_complete():
    with tempfile.TemporaryDirectory() as tmp:
        inventory = full_inventory(_analyze(Path(tmp)))

    counts = inventory['stats']['nodeCounts']
    assert counts['BWProcess'] == 3
    assert counts['SharedResource'] == 4
    assert inventory['entryPoints'], 'no entry points'
    assert inventory['integrationSurface'], 'no integration surface'
    assert inventory['meta']['coverage']['artifactCoverage'] == 100.0


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
