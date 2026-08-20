"""Cypher cookbook for the Oracle graph.

The questions an analyst actually asks of a PL/SQL estate, expressed as Cypher
for teams who load the graph into Neo4j. Emitted as a runnable `.cypher` file
and surfaced by the `queries` command.
"""
from __future__ import annotations

from typing import Dict, List

from analyzer_core.graph.cookbook import render_cookbook as _render_cookbook
from analyzer_core.graph.cookbook import render_markdown as _render_markdown

TITLE = 'Oracle PL/SQL Knowledge Graph'

CYPHER_COOKBOOK: List[Dict[str, str]] = [
    {
        'id': 'node-counts',
        'title': 'Node counts by label (verification)',
        'purpose': 'Confirm the import populated every expected label.',
        'cypher': 'MATCH (n)\nRETURN labels(n)[0] AS NodeType, count(n) AS Count\n'
                  'ORDER BY Count DESC;',
    },
    {
        'id': 'rel-counts',
        'title': 'Relationship counts by type (verification)',
        'purpose': 'Confirm every semantic edge type survived the import.',
        'cypher': 'MATCH ()-[r]->()\nRETURN type(r) AS RelationshipType, count(r) AS Count\n'
                  'ORDER BY Count DESC;',
    },
    {
        'id': 'writers-of-table',
        'title': 'Which program units modify a table',
        'purpose': 'The question a change to a table starts with. Uses the '
                   'WRITES_TO roll-up, so inserts, updates and deletes all count.',
        'cypher': 'MATCH (u:DbProgramUnit)-[:EXECUTES_SQL]->(:SqlStatement)'
                  '-[:WRITES_TO]->(t:DbTable)\n'
                  'WHERE t.name = $objectName\n'
                  'RETURN DISTINCT u.packageName AS Package, u.name AS Unit,\n'
                  '       u.filePath AS File, u.lineStart AS Line\n'
                  'ORDER BY Package, Unit;',
    },
    {
        'id': 'access-verbs',
        'title': 'Exactly how each unit touches a table',
        'purpose': 'The precise verb, not the roll-up: separates a reader from '
                   'an inserter from a deleter.',
        'cypher': 'MATCH (u:DbProgramUnit)-[:EXECUTES_SQL]->(s:SqlStatement)'
                  '-[r:READS_FROM|INSERTS_INTO|UPDATES|DELETES_FROM]->(t:DbTable)\n'
                  'WHERE t.name = $objectName\n'
                  'RETURN u.name AS Unit, type(r) AS Access, count(s) AS Statements\n'
                  'ORDER BY Unit, Access;',
    },
    {
        'id': 'blast-radius',
        'title': 'Blast radius of a table change',
        'purpose': 'Every unit that reaches the table, directly or through a '
                   'call chain, with the depth at which it does.',
        'cypher': 'MATCH path = (t:DbTable {name: $objectName})\n'
                  '             <-[:READS_FROM|WRITES_TO]-(:SqlStatement)\n'
                  '             <-[:EXECUTES_SQL]-(:DbProgramUnit)\n'
                  '             <-[:CALLS*0..6]-(caller:DbProgramUnit)\n'
                  'RETURN DISTINCT caller.packageName AS Package, caller.name AS Unit,\n'
                  '       length(path) AS Depth\n'
                  'ORDER BY Depth, Package, Unit;',
    },
    {
        'id': 'call-graph',
        'title': 'Call chain from a unit',
        'purpose': 'The full execution path, which is what a rewrite has to '
                   'preserve.',
        'cypher': 'MATCH path = (u:DbProgramUnit {name: $unitName})-[:CALLS*1..10]->(target)\n'
                  'RETURN path\nLIMIT 100;',
    },
    {
        'id': 'entry-points',
        'title': 'Entry points',
        'purpose': 'What the outside world can invoke: units published by a '
                   'package spec, standalone units, and triggers.',
        'cypher': 'MATCH (spec:PackageSpec)-[:HAS_UNIT]->(u:DbProgramUnit)\n'
                  'RETURN u.packageName AS Package, u.name AS Unit, '
                  "'PUBLISHED' AS Kind\n"
                  'UNION\n'
                  'MATCH (u:DbProgramUnit {isStandalone: true})\n'
                  "RETURN '' AS Package, u.name AS Unit, 'STANDALONE' AS Kind\n"
                  'UNION\n'
                  'MATCH (t:DbTrigger)-[:FIRES_ON]->(tab:DbTable)\n'
                  "RETURN tab.name AS Package, t.name AS Unit, 'TRIGGER' AS Kind;",
    },
    {
        'id': 'spec-change-impact',
        'title': 'Callers broken by a package spec change',
        'purpose': 'A spec change breaks every caller; the same change to a '
                   'body does not. This is why the two are separate nodes.',
        'cypher': 'MATCH (p:DbPackage {name: $objectName})-[:HAS_SPEC]->(:PackageSpec)\n'
                  '      -[:HAS_UNIT]->(published:DbProgramUnit)\n'
                  'OPTIONAL MATCH (caller:DbProgramUnit)-[:CALLS]->(published)\n'
                  'RETURN published.name AS PublishedUnit,\n'
                  '       collect(DISTINCT caller.packageName + \'.\' + caller.name) AS Callers\n'
                  'ORDER BY PublishedUnit;',
    },
    {
        'id': 'hotspots',
        'title': 'Most depended-upon objects',
        'purpose': 'Where a change costs most. Sequence the migration around '
                   'these.',
        'cypher': 'MATCH (n)<-[r:CALLS|READS_FROM|WRITES_TO|DEPENDS_ON]-()\n'
                  'WHERE n:DbTable OR n:DbView OR n:DbPackage OR n:DbProgramUnit\n'
                  'RETURN labels(n)[0] AS Type, n.name AS Name, count(r) AS Dependents\n'
                  'ORDER BY Dependents DESC\nLIMIT 25;',
    },
    {
        'id': 'view-lineage',
        'title': 'View lineage',
        'purpose': 'What a view is built from, through any depth of nesting.',
        'cypher': 'MATCH path = (v:DbView)-[:DEPENDS_ON*1..5]->(t:DbTable)\n'
                  'RETURN v.name AS View, t.name AS BaseTable, length(path) AS Depth\n'
                  'ORDER BY View, Depth;',
    },
    {
        'id': 'table-lineage',
        'title': 'Everything that feeds a table',
        'purpose': 'Column-level provenance starts here: which statements write '
                   'this table, and what they read to do it.',
        'cypher': 'MATCH (target:DbTable {name: $objectName})<-[:WRITES_TO]-(s:SqlStatement)\n'
                  'OPTIONAL MATCH (s)-[:READS_FROM]->(src:DbTable)\n'
                  'OPTIONAL MATCH (u:DbProgramUnit)-[:EXECUTES_SQL]->(s)\n'
                  'RETURN u.name AS Unit, s.verb AS Verb,\n'
                  '       collect(DISTINCT src.name) AS ReadsFrom\n'
                  'ORDER BY Unit;',
    },
    {
        'id': 'column-usage',
        'title': 'What touches a column',
        'purpose': 'The question a column rename or a type change starts with. '
                   'Reports the statement and the unit that runs it; the graph '
                   'does not claim which column feeds which.',
        'cypher': 'MATCH (c:DbColumn {name: $columnName})<-[:REFERENCES_COLUMN]-(s:SqlStatement)\n'
                  'OPTIONAL MATCH (u:DbProgramUnit)-[:EXECUTES_SQL]->(s)\n'
                  'RETURN c.tableName AS Table, c.name AS Column,\n'
                  '       collect(DISTINCT u.name) AS Units, s.verb AS Verb\n'
                  'ORDER BY Table, Column;',
    },
    {
        'id': 'join-partners',
        'title': 'Tables that are queried together',
        'purpose': 'Where a composite index or a denormalisation would pay. '
                   'JOINS is only emitted when a statement combines more than '
                   'one table, so a plain read never appears here.',
        'cypher': 'MATCH (s:SqlStatement)-[:JOINS]->(t:DbTable)\n'
                  'WITH s, collect(DISTINCT t.name) AS Tables\n'
                  'WHERE size(Tables) > 1\n'
                  'RETURN Tables, count(*) AS Statements\n'
                  'ORDER BY Statements DESC\n'
                  'LIMIT 25;',
    },
    {
        'id': 'type-dependents',
        'title': 'What depends on a user-defined type',
        'purpose': 'A type change is a recompile for everything that declares '
                   'it, and that dependency is invisible in the data-access '
                   'edges.',
        'cypher': 'MATCH (dependent)-[:USES_TYPE]->(t:DbType)\n'
                  'RETURN t.name AS Type, t.typeCategory AS Category,\n'
                  '       collect(dependent.name) AS Dependents\n'
                  'ORDER BY Type;',
    },
    {
        'id': 'business-to-data',
        'title': 'Business function down to the tables it changes',
        'purpose': 'The chain a modernisation conversation runs on: capability '
                   'to code to data. Check `origin` before quoting it -- a '
                   'derived seed is a starting point, a declared one is a fact.',
        'cypher': 'MATCH (d:BusinessDomain)<-[:PART_OF_DOMAIN]-(f:BusinessFunction)\n'
                  '      -[:IMPLEMENTED_BY]->(u:DbProgramUnit)\n'
                  'MATCH (u)-[:EXECUTES_SQL]->(:SqlStatement)-[:WRITES_TO]->(t:DbTable)\n'
                  'RETURN d.name AS Domain, f.name AS Function, f.origin AS Origin,\n'
                  '       f.confidence AS Confidence, u.name AS Unit,\n'
                  '       collect(DISTINCT t.name) AS Writes\n'
                  'ORDER BY Domain, Function;',
    },
    {
        'id': 'untested-entry-points',
        'title': 'Entry points with no test',
        'purpose': 'Where a rewrite carries the most risk: callable from '
                   'outside, changes data, and nothing covers it.',
        'cypher': 'MATCH (u:DbProgramUnit)\n'
                  'WHERE (u.isPublished OR u.isStandalone) AND NOT u.declaredOnly\n'
                  '  AND NOT (u)-[:HAS_TEST]->(:TestCase)\n'
                  '  AND (u)-[:EXECUTES_SQL]->(:SqlStatement)-[:WRITES_TO]->()\n'
                  'RETURN u.owner AS Schema, u.packageName AS Package,\n'
                  '       u.name AS Unit, u.complexity AS Complexity\n'
                  'ORDER BY Complexity DESC;',
    },
    {
        'id': 'test-coverage',
        'title': 'What covers a program unit',
        'purpose': 'Read before changing a unit: the cases that exercise it, '
                   'and the suite they live in.',
        'cypher': 'MATCH (u:DbProgramUnit)-[:HAS_TEST]->(c:TestCase)\n'
                  'RETURN u.packageName AS Package, u.name AS Unit,\n'
                  '       c.suite AS Suite, collect(c.displayName) AS Cases\n'
                  'ORDER BY Package, Unit;',
    },
    {
        'id': 'trigger-map',
        'title': 'Triggers and what they fire on',
        'purpose': 'Hidden control flow: a write to a table may run code the '
                   'caller never mentions.',
        'cypher': 'MATCH (t:DbTrigger)-[f:FIRES_ON]->(tab:DbTable)\n'
                  'RETURN tab.name AS Table, t.name AS Trigger,\n'
                  '       t.triggeringEvent AS Event, t.filePath AS File\n'
                  'ORDER BY Table, Trigger;',
    },
    {
        'id': 'dynamic-sql',
        'title': 'Where dependency analysis stops',
        'purpose': 'Units that build SQL at runtime. Their dependencies are not '
                   'in this graph and must not be assumed absent.',
        'cypher': 'MATCH (u:DbProgramUnit {hasDynamicSql: true})\n'
                  'RETURN u.packageName AS Package, u.name AS Unit,\n'
                  '       u.filePath AS File, u.lineStart AS Line\n'
                  'ORDER BY Package, Unit;',
    },
    {
        'id': 'unresolved',
        'title': 'Unresolved references',
        'purpose': 'Names the analysis saw but could not bind. Quote this '
                   'alongside any completeness claim.',
        'cypher': 'MATCH (src)-[:UNRESOLVED]->(u:UnresolvedRef)\n'
                  'RETURN u.name AS Reference, u.kinds AS Kinds,\n'
                  '       count(src) AS ReferencedBy\n'
                  'ORDER BY ReferencedBy DESC;',
    },
    {
        'id': 'findings',
        'title': 'Findings by severity',
        'purpose': 'The rule catalogue output, most severe first.',
        'cypher': 'MATCH (target)-[:HAS_ISSUE]->(i:Issue)\n'
                  'OPTIONAL MATCH (i)-[:HAS_RECOMMENDATION]->(r:Recommendation)\n'
                  'RETURN i.severity AS Severity, i.ruleId AS Rule,\n'
                  '       i.targetName AS Target, i.description AS Finding,\n'
                  '       r.text AS Recommendation\n'
                  'ORDER BY CASE i.severity WHEN \'CRITICAL\' THEN 0 '
                  "WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END, Rule;",
    },
    {
        'id': 'dead-code',
        'title': 'Units nothing calls',
        'purpose': 'Private body units with no caller in the analysed tree. '
                   'Check the dynamic-SQL list before deleting any of them.',
        'cypher': 'MATCH (body:PackageBody)-[:HAS_UNIT]->(u:DbProgramUnit)\n'
                  'WHERE NOT ()-[:CALLS]->(u)\n'
                  '  AND NOT (:PackageSpec)-[:HAS_UNIT]->(u)\n'
                  'RETURN u.packageName AS Package, u.name AS Unit, u.loc AS Lines\n'
                  'ORDER BY Lines DESC;',
    },
    {
        'id': 'churn-vs-complexity',
        'title': 'Complex code that changes often',
        'purpose': 'Where defects concentrate: high complexity plus high churn.',
        'cypher': 'MATCH (f:File)<-[:CHANGED]-(c:Commit)\n'
                  'WITH f, count(c) AS Churn\n'
                  'MATCH (f)-[:DEFINES]->()<-[:HAS_UNIT*0..1]-()\n'
                  'MATCH (u:DbProgramUnit) WHERE u.filePath = f.filePath\n'
                  'RETURN f.filePath AS File, Churn,\n'
                  '       round(sum(u.complexity)) AS TotalComplexity\n'
                  'ORDER BY Churn * TotalComplexity DESC\nLIMIT 25;',
    },
]


def render_cookbook() -> str:
    return _render_cookbook(CYPHER_COOKBOOK, TITLE,
                            param_hint=':param objectName => "ORDERS"')


def render_markdown() -> str:
    return _render_markdown(
        CYPHER_COOKBOOK, TITLE,
        intro='Set `$objectName`, `$unitName` or `$columnName` in Neo4j Browser '
              'before running a parameterised query, for example '
              '`:param objectName => "ORDERS"`.')
