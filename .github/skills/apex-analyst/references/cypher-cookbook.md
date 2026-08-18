# Oracle APEX Knowledge Graph — Cypher Query Cookbook

Run these in Neo4j Browser after loading `neo4j_nodes.csv` / `neo4j_relationships.csv` with `scripts/push_to_neo4j.py`, or after replaying `neo4j_import.cypher`.

| id | Question |
|---|---|
| `node-counts` | Node counts by label (verification) |
| `rel-counts` | Relationship counts by type (verification) |
| `impact-procedure` | Impact of changing a procedure |
| `impact-table` | Impact of changing a table, with the access mode |
| `column-lineage` | Column lineage |
| `orphan-units` | Program units no page reaches |
| `unreachable-pages` | Unreachable pages |
| `complexity-ranking` | Page complexity leaderboard |
| `unsecured-writes` | Unsecured pages that write to the database |
| `duplicate-sql` | Duplicated SQL (extraction candidates) |
| `issues-by-severity` | Findings by severity |
| `release-impact` | Release impact from a commit range |
| `business-traceability` | Business function traceability |
| `provenance-audit` | Provenance and confidence audit |
| `unresolved-references` | Unresolved database references |
| `page-dependency-tree` | Everything one page depends on |
| `table-hotspots` | Change hotspots |

## Node counts by label (verification)

_Confirm the import populated every expected label._

```cypher
MATCH (n)
RETURN labels(n)[0] AS NodeType, count(n) AS Count
ORDER BY Count DESC;
```

## Relationship counts by type (verification)

_Confirm every semantic edge type is present._

```cypher
MATCH ()-[r]->()
RETURN type(r) AS RelationshipType, count(r) AS Count
ORDER BY Count DESC;
```

## Impact of changing a procedure

_Which pages break if this package procedure changes._

```cypher
MATCH (u:DbProgramUnit {name: $unitName})
MATCH path = (p:ApexPage)-[:CONTAINS_REGION|CONTAINS_PROCESS|
  CONTAINS_DYNAMIC_ACTION|CONTAINS_ACTION|CONTAINS_VALIDATION|
  EXECUTES_SQL|EXECUTES_PLSQL|CALLS|DEPENDS_ON|READS_FROM|
  SOURCED_FROM*1..8]->(u)
RETURN DISTINCT p.pageId AS Page, p.name AS Name, p.tier AS Tier,
       min(length(path)) AS Hops
ORDER BY Hops, Page;
```

## Impact of changing a table, with the access mode

_Which pages read it, which write it, and through what._

```cypher
MATCH (t:DbTable {name: $tableName})
MATCH (p:ApexPage)-[:CONTAINS_REGION|CONTAINS_PROCESS|
  CONTAINS_DYNAMIC_ACTION|CONTAINS_ACTION*1..3]->(c)
MATCH (c)-[:EXECUTES_SQL|EXECUTES_PLSQL|SOURCED_FROM]->(code)
MATCH (code)-[r:READS_FROM|WRITES_TO|INSERTS_INTO|UPDATES|
  DELETES_FROM]->(t)
RETURN p.pageId AS Page, p.name AS PageName,
       collect(DISTINCT type(r)) AS Access,
       collect(DISTINCT c.name)  AS Components
ORDER BY Page;
```

## Column lineage

_Which pages use a specific column, and through which component._

```cypher
MATCH (col:DbColumn {tableName: $tableName, name: $columnName})
MATCH (user)-[:REFERENCES_COLUMN]->(col)
MATCH (p:ApexPage)-[*1..6]->(user)
RETURN DISTINCT p.pageId AS Page, p.name AS PageName,
       labels(user)[0] AS Via, user.name AS Detail
ORDER BY Page;
```

## Program units no page reaches

_Dead PL/SQL: nothing in the application can invoke it._

```cypher
MATCH (u:DbProgramUnit)
WHERE NOT EXISTS {
  MATCH (:ApexPage)-[:CONTAINS_REGION|CONTAINS_PROCESS|
    CONTAINS_DYNAMIC_ACTION|CONTAINS_ACTION|EXECUTES_SQL|
    EXECUTES_PLSQL|CALLS|DEPENDS_ON*1..8]->(u)
}
AND NOT EXISTS { MATCH (:DbTrigger)-[:EXECUTES_PLSQL|CALLS*1..4]->(u) }
RETURN u.owner AS Owner, u.packageName AS Package, u.name AS Unit
ORDER BY Owner, Package, Unit;
```

## Unreachable pages

_No branch, button, list entry or navigation entry targets them._

```cypher
MATCH (p:ApexPage)
WHERE NOT ()-[:NAVIGATES_TO]->(p)
  AND NOT p.pageId IN [0, 1, 101]
RETURN p.pageId AS Page, p.name AS Name, p.tier AS Tier
ORDER BY Page;
```

## Page complexity leaderboard

_Where the risk and the effort are concentrated._

```cypher
MATCH (p:ApexPage)
RETURN p.pageId AS Page, p.name AS Name, p.complexityScore AS Score,
       p.tier AS Tier, p.regionCount AS Regions,
       p.processCount AS Processes, p.tableCount AS Tables,
       p.writeCount AS Writes
ORDER BY Score DESC LIMIT 25;
```

## Unsecured pages that write to the database

_The highest-value security finding in most applications._

```cypher
MATCH (p:ApexPage)-[:CONTAINS_PROCESS]->(proc:ApexProcess)
MATCH (proc)-[:EXECUTES_PLSQL|EXECUTES_SQL]->(code)
MATCH (code)-[:WRITES_TO]->(t:DbTable)
WHERE NOT (p)-[:SECURED_BY]->(:ApexAuthorization)
RETURN p.pageId AS Page, p.name AS Name,
       collect(DISTINCT t.name) AS TablesWritten
ORDER BY size(TablesWritten) DESC;
```

## Duplicated SQL (extraction candidates)

_One statement executed by many components: extract to a view._

```cypher
MATCH (s:SqlStatement)<-[:EXECUTES_SQL]-(c)
WITH s, count(DISTINCT c) AS users, collect(DISTINCT c.name)[0..5] AS sample
WHERE users >= 3
RETURN s.sqlHash AS Hash, users AS UsedBy, sample AS Sample,
       left(s.text, 120) AS Preview
ORDER BY users DESC;
```

## Findings by severity

_The rule catalogue output, ranked._

```cypher
MATCH (n)-[:HAS_ISSUE]->(i:Issue)
OPTIONAL MATCH (i)-[:HAS_RECOMMENDATION]->(r:Recommendation)
RETURN i.severity AS Severity, i.ruleId AS Rule, i.title AS Title,
       n.name AS Component, i.pageId AS Page, r.action AS Recommendation
ORDER BY CASE i.severity WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1
         WHEN 'MEDIUM' THEN 2 ELSE 3 END, Rule;
```

## Release impact from a commit range

_What changed, and which database objects it reaches._

```cypher
MATCH (c:Commit)-[:CHANGED]->(f:File)-[:DEFINES]->(n)
WHERE c.sha IN $shas
OPTIONAL MATCH (n)-[*1..6]->(o:DbObject)
RETURN labels(n)[0] AS Component, n.name AS Name,
       collect(DISTINCT o.owner + '.' + o.name)[0..10] AS DbObjects
ORDER BY Component, Name;
```

## Business function traceability

_From a business function down to the tables it writes._

```cypher
MATCH (bf:BusinessFunction)-[:IMPLEMENTED_BY]->(entry)
MATCH path = (entry)-[:CONTAINS_PROCESS|EXECUTES_PLSQL|EXECUTES_SQL|
  CALLS|WRITES_TO*1..8]->(t:DbTable)
RETURN bf.name AS Function, bf.domain AS Domain,
       collect(DISTINCT t.name) AS TablesWritten
ORDER BY Domain, Function;
```

## Provenance and confidence audit

_How much of the graph is asserted versus inferred._

```cypher
MATCH ()-[r]->()
RETURN type(r) AS Rel, coalesce(r.resolution, 'asserted') AS Resolution,
       count(*) AS Count,
       round(avg(coalesce(r.confidence, 1.0)), 2) AS AvgConfidence
ORDER BY Count DESC;
```

## Unresolved database references

_Where the graph knows it does not know._

```cypher
MATCH (n)-[r]->(u:Unresolved)
RETURN u.name AS MissingObject, type(r) AS Access,
       collect(DISTINCT labels(n)[0] + ':' + n.name)[0..10] AS ReferencedBy,
       count(*) AS References
ORDER BY References DESC;
```

## Everything one page depends on

_The full downstream chain for a single page._

```cypher
MATCH path = (p:ApexPage {pageId: $pageId})-[:CONTAINS_REGION|
  CONTAINS_PROCESS|CONTAINS_ITEM|CONTAINS_DYNAMIC_ACTION|
  CONTAINS_ACTION|EXECUTES_SQL|EXECUTES_PLSQL|READS_FROM|WRITES_TO|
  CALLS|SOURCED_FROM|USES_LOV*1..7]->(dep)
RETURN DISTINCT labels(dep)[0] AS Type, dep.name AS Name,
       min(length(path)) AS Hops
ORDER BY Hops, Type, Name;
```

## Change hotspots

_High fan-in database objects: change these carefully._

```cypher
MATCH (o:DbObject)
WHERE o.fanIn IS NOT NULL AND o.fanIn > 0
RETURN labels(o)[0] AS Type, o.owner AS Owner, o.name AS Name,
       o.fanIn AS PagesReaching
ORDER BY PagesReaching DESC LIMIT 25;
```
