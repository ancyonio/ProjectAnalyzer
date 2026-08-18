"""Cypher cookbook for the APEX graph (specification §16).

The same questions the local engine answers in memory, expressed as Cypher
for teams who load the graph into Neo4j. Emitted as a `.cypher` file so it is
copy-pasteable into Neo4j Browser, and surfaced by the `queries` command.
"""
from __future__ import annotations

from typing import Dict, List

from analyzer_core.graph.cookbook import render_cookbook as _render_cookbook
from analyzer_core.graph.cookbook import render_markdown as _render_markdown

TITLE = 'Oracle APEX Knowledge Graph'

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
        'purpose': 'Confirm every semantic edge type is present.',
        'cypher': 'MATCH ()-[r]->()\nRETURN type(r) AS RelationshipType, count(r) AS Count\n'
                  'ORDER BY Count DESC;',
    },
    {
        'id': 'impact-procedure',
        'title': 'Impact of changing a procedure',
        'purpose': 'Which pages break if this package procedure changes.',
        'cypher': "MATCH (u:DbProgramUnit {name: $unitName})\n"
                  "MATCH path = (p:ApexPage)-[:CONTAINS_REGION|CONTAINS_PROCESS|\n"
                  "  CONTAINS_DYNAMIC_ACTION|CONTAINS_ACTION|CONTAINS_VALIDATION|\n"
                  "  EXECUTES_SQL|EXECUTES_PLSQL|CALLS|DEPENDS_ON|READS_FROM|\n"
                  "  SOURCED_FROM*1..8]->(u)\n"
                  "RETURN DISTINCT p.pageId AS Page, p.name AS Name, p.tier AS Tier,\n"
                  "       min(length(path)) AS Hops\n"
                  "ORDER BY Hops, Page;",
    },
    {
        'id': 'impact-table',
        'title': 'Impact of changing a table, with the access mode',
        'purpose': 'Which pages read it, which write it, and through what.',
        'cypher': "MATCH (t:DbTable {name: $tableName})\n"
                  "MATCH (p:ApexPage)-[:CONTAINS_REGION|CONTAINS_PROCESS|\n"
                  "  CONTAINS_DYNAMIC_ACTION|CONTAINS_ACTION*1..3]->(c)\n"
                  "MATCH (c)-[:EXECUTES_SQL|EXECUTES_PLSQL|SOURCED_FROM]->(code)\n"
                  "MATCH (code)-[r:READS_FROM|WRITES_TO|INSERTS_INTO|UPDATES|\n"
                  "  DELETES_FROM]->(t)\n"
                  "RETURN p.pageId AS Page, p.name AS PageName,\n"
                  "       collect(DISTINCT type(r)) AS Access,\n"
                  "       collect(DISTINCT c.name)  AS Components\n"
                  "ORDER BY Page;",
    },
    {
        'id': 'column-lineage',
        'title': 'Column lineage',
        'purpose': 'Which pages use a specific column, and through which component.',
        'cypher': "MATCH (col:DbColumn {tableName: $tableName, name: $columnName})\n"
                  "MATCH (user)-[:REFERENCES_COLUMN]->(col)\n"
                  "MATCH (p:ApexPage)-[*1..6]->(user)\n"
                  "RETURN DISTINCT p.pageId AS Page, p.name AS PageName,\n"
                  "       labels(user)[0] AS Via, user.name AS Detail\n"
                  "ORDER BY Page;",
    },
    {
        'id': 'orphan-units',
        'title': 'Program units no page reaches',
        'purpose': 'Dead PL/SQL: nothing in the application can invoke it.',
        'cypher': "MATCH (u:DbProgramUnit)\n"
                  "WHERE NOT EXISTS {\n"
                  "  MATCH (:ApexPage)-[:CONTAINS_REGION|CONTAINS_PROCESS|\n"
                  "    CONTAINS_DYNAMIC_ACTION|CONTAINS_ACTION|EXECUTES_SQL|\n"
                  "    EXECUTES_PLSQL|CALLS|DEPENDS_ON*1..8]->(u)\n"
                  "}\n"
                  "AND NOT EXISTS { MATCH (:DbTrigger)-[:EXECUTES_PLSQL|CALLS*1..4]->(u) }\n"
                  "RETURN u.owner AS Owner, u.packageName AS Package, u.name AS Unit\n"
                  "ORDER BY Owner, Package, Unit;",
    },
    {
        'id': 'unreachable-pages',
        'title': 'Unreachable pages',
        'purpose': 'No branch, button, list entry or navigation entry targets them.',
        'cypher': "MATCH (p:ApexPage)\n"
                  "WHERE NOT ()-[:NAVIGATES_TO]->(p)\n"
                  "  AND NOT p.pageId IN [0, 1, 101]\n"
                  "RETURN p.pageId AS Page, p.name AS Name, p.tier AS Tier\n"
                  "ORDER BY Page;",
    },
    {
        'id': 'complexity-ranking',
        'title': 'Page complexity leaderboard',
        'purpose': 'Where the risk and the effort are concentrated.',
        'cypher': "MATCH (p:ApexPage)\n"
                  "RETURN p.pageId AS Page, p.name AS Name, p.complexityScore AS Score,\n"
                  "       p.tier AS Tier, p.regionCount AS Regions,\n"
                  "       p.processCount AS Processes, p.tableCount AS Tables,\n"
                  "       p.writeCount AS Writes\n"
                  "ORDER BY Score DESC LIMIT 25;",
    },
    {
        'id': 'unsecured-writes',
        'title': 'Unsecured pages that write to the database',
        'purpose': 'The highest-value security finding in most applications.',
        'cypher': "MATCH (p:ApexPage)-[:CONTAINS_PROCESS]->(proc:ApexProcess)\n"
                  "MATCH (proc)-[:EXECUTES_PLSQL|EXECUTES_SQL]->(code)\n"
                  "MATCH (code)-[:WRITES_TO]->(t:DbTable)\n"
                  "WHERE NOT (p)-[:SECURED_BY]->(:ApexAuthorization)\n"
                  "RETURN p.pageId AS Page, p.name AS Name,\n"
                  "       collect(DISTINCT t.name) AS TablesWritten\n"
                  "ORDER BY size(TablesWritten) DESC;",
    },
    {
        'id': 'duplicate-sql',
        'title': 'Duplicated SQL (extraction candidates)',
        'purpose': 'One statement executed by many components: extract to a view.',
        'cypher': "MATCH (s:SqlStatement)<-[:EXECUTES_SQL]-(c)\n"
                  "WITH s, count(DISTINCT c) AS users, collect(DISTINCT c.name)[0..5] AS sample\n"
                  "WHERE users >= 3\n"
                  "RETURN s.sqlHash AS Hash, users AS UsedBy, sample AS Sample,\n"
                  "       left(s.text, 120) AS Preview\n"
                  "ORDER BY users DESC;",
    },
    {
        'id': 'issues-by-severity',
        'title': 'Findings by severity',
        'purpose': 'The rule catalogue output, ranked.',
        'cypher': "MATCH (n)-[:HAS_ISSUE]->(i:Issue)\n"
                  "OPTIONAL MATCH (i)-[:HAS_RECOMMENDATION]->(r:Recommendation)\n"
                  "RETURN i.severity AS Severity, i.ruleId AS Rule, i.title AS Title,\n"
                  "       n.name AS Component, i.pageId AS Page, r.action AS Recommendation\n"
                  "ORDER BY CASE i.severity WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1\n"
                  "         WHEN 'MEDIUM' THEN 2 ELSE 3 END, Rule;",
    },
    {
        'id': 'release-impact',
        'title': 'Release impact from a commit range',
        'purpose': 'What changed, and which database objects it reaches.',
        'cypher': "MATCH (c:Commit)-[:CHANGED]->(f:File)-[:DEFINES]->(n)\n"
                  "WHERE c.sha IN $shas\n"
                  "OPTIONAL MATCH (n)-[*1..6]->(o:DbObject)\n"
                  "RETURN labels(n)[0] AS Component, n.name AS Name,\n"
                  "       collect(DISTINCT o.owner + '.' + o.name)[0..10] AS DbObjects\n"
                  "ORDER BY Component, Name;",
    },
    {
        'id': 'business-traceability',
        'title': 'Business function traceability',
        'purpose': 'From a business function down to the tables it writes.',
        'cypher': "MATCH (bf:BusinessFunction)-[:IMPLEMENTED_BY]->(entry)\n"
                  "MATCH path = (entry)-[:CONTAINS_PROCESS|EXECUTES_PLSQL|EXECUTES_SQL|\n"
                  "  CALLS|WRITES_TO*1..8]->(t:DbTable)\n"
                  "RETURN bf.name AS Function, bf.domain AS Domain,\n"
                  "       collect(DISTINCT t.name) AS TablesWritten\n"
                  "ORDER BY Domain, Function;",
    },
    {
        'id': 'provenance-audit',
        'title': 'Provenance and confidence audit',
        'purpose': 'How much of the graph is asserted versus inferred.',
        'cypher': "MATCH ()-[r]->()\n"
                  "RETURN type(r) AS Rel, coalesce(r.resolution, 'asserted') AS Resolution,\n"
                  "       count(*) AS Count,\n"
                  "       round(avg(coalesce(r.confidence, 1.0)), 2) AS AvgConfidence\n"
                  "ORDER BY Count DESC;",
    },
    {
        'id': 'unresolved-references',
        'title': 'Unresolved database references',
        'purpose': 'Where the graph knows it does not know.',
        'cypher': "MATCH (n)-[r]->(u:Unresolved)\n"
                  "RETURN u.name AS MissingObject, type(r) AS Access,\n"
                  "       collect(DISTINCT labels(n)[0] + ':' + n.name)[0..10] AS ReferencedBy,\n"
                  "       count(*) AS References\n"
                  "ORDER BY References DESC;",
    },
    {
        'id': 'page-dependency-tree',
        'title': 'Everything one page depends on',
        'purpose': 'The full downstream chain for a single page.',
        'cypher': "MATCH path = (p:ApexPage {pageId: $pageId})-[:CONTAINS_REGION|\n"
                  "  CONTAINS_PROCESS|CONTAINS_ITEM|CONTAINS_DYNAMIC_ACTION|\n"
                  "  CONTAINS_ACTION|EXECUTES_SQL|EXECUTES_PLSQL|READS_FROM|WRITES_TO|\n"
                  "  CALLS|SOURCED_FROM|USES_LOV*1..7]->(dep)\n"
                  "RETURN DISTINCT labels(dep)[0] AS Type, dep.name AS Name,\n"
                  "       min(length(path)) AS Hops\n"
                  "ORDER BY Hops, Type, Name;",
    },
    {
        'id': 'table-hotspots',
        'title': 'Change hotspots',
        'purpose': 'High fan-in database objects: change these carefully.',
        'cypher': "MATCH (o:DbObject)\n"
                  "WHERE o.fanIn IS NOT NULL AND o.fanIn > 0\n"
                  "RETURN labels(o)[0] AS Type, o.owner AS Owner, o.name AS Name,\n"
                  "       o.fanIn AS PagesReaching\n"
                  "ORDER BY PagesReaching DESC LIMIT 25;",
    },
]


def render_cookbook() -> str:
    return _render_cookbook(CYPHER_COOKBOOK, TITLE,
                            ':param tableName => "ORDERS"')


def render_markdown() -> str:
    return _render_markdown(
        CYPHER_COOKBOOK, TITLE,
        'Run these in Neo4j Browser after loading `neo4j_nodes.csv` / '
        '`neo4j_relationships.csv` with `scripts/push_to_neo4j.py`, or after '
        'replaying `neo4j_import.cypher`.')
