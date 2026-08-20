<!-- Generated from tools/oracle_analyzer/graph/queries.py.
     Regenerate with:
       PYTHONPATH=tools python -c "from oracle_analyzer.graph.queries import render_markdown; print(render_markdown())"
     Do not hand-edit: the analyzer emits the same cookbook into
     analysis_output_oracle/ANALYSIS_QUERIES.md, and the two must agree. -->
# Oracle PL/SQL Knowledge Graph — Cypher Query Cookbook

Set `$objectName`, `$unitName` or `$columnName` in Neo4j Browser before running a parameterised query, for example `:param objectName => "ORDERS"`.

| id | Question |
|---|---|
| `node-counts` | Node counts by label (verification) |
| `rel-counts` | Relationship counts by type (verification) |
| `writers-of-table` | Which program units modify a table |
| `access-verbs` | Exactly how each unit touches a table |
| `blast-radius` | Blast radius of a table change |
| `call-graph` | Call chain from a unit |
| `entry-points` | Entry points |
| `spec-change-impact` | Callers broken by a package spec change |
| `hotspots` | Most depended-upon objects |
| `view-lineage` | View lineage |
| `table-lineage` | Everything that feeds a table |
| `column-usage` | What touches a column |
| `join-partners` | Tables that are queried together |
| `type-dependents` | What depends on a user-defined type |
| `business-to-data` | Business function down to the tables it changes |
| `untested-entry-points` | Entry points with no test |
| `test-coverage` | What covers a program unit |
| `trigger-map` | Triggers and what they fire on |
| `dynamic-sql` | Where dependency analysis stops |
| `unresolved` | Unresolved references |
| `findings` | Findings by severity |
| `dead-code` | Units nothing calls |
| `churn-vs-complexity` | Complex code that changes often |

## Node counts by label (verification)

_Confirm the import populated every expected label._

```cypher
MATCH (n)
RETURN labels(n)[0] AS NodeType, count(n) AS Count
ORDER BY Count DESC;
```

## Relationship counts by type (verification)

_Confirm every semantic edge type survived the import._

```cypher
MATCH ()-[r]->()
RETURN type(r) AS RelationshipType, count(r) AS Count
ORDER BY Count DESC;
```

## Which program units modify a table

_The question a change to a table starts with. Uses the WRITES_TO roll-up, so inserts, updates and deletes all count._

```cypher
MATCH (u:DbProgramUnit)-[:EXECUTES_SQL]->(:SqlStatement)-[:WRITES_TO]->(t:DbTable)
WHERE t.name = $objectName
RETURN DISTINCT u.packageName AS Package, u.name AS Unit,
       u.filePath AS File, u.lineStart AS Line
ORDER BY Package, Unit;
```

## Exactly how each unit touches a table

_The precise verb, not the roll-up: separates a reader from an inserter from a deleter._

```cypher
MATCH (u:DbProgramUnit)-[:EXECUTES_SQL]->(s:SqlStatement)-[r:READS_FROM|INSERTS_INTO|UPDATES|DELETES_FROM]->(t:DbTable)
WHERE t.name = $objectName
RETURN u.name AS Unit, type(r) AS Access, count(s) AS Statements
ORDER BY Unit, Access;
```

## Blast radius of a table change

_Every unit that reaches the table, directly or through a call chain, with the depth at which it does._

```cypher
MATCH path = (t:DbTable {name: $objectName})
             <-[:READS_FROM|WRITES_TO]-(:SqlStatement)
             <-[:EXECUTES_SQL]-(:DbProgramUnit)
             <-[:CALLS*0..6]-(caller:DbProgramUnit)
RETURN DISTINCT caller.packageName AS Package, caller.name AS Unit,
       length(path) AS Depth
ORDER BY Depth, Package, Unit;
```

## Call chain from a unit

_The full execution path, which is what a rewrite has to preserve._

```cypher
MATCH path = (u:DbProgramUnit {name: $unitName})-[:CALLS*1..10]->(target)
RETURN path
LIMIT 100;
```

## Entry points

_What the outside world can invoke: units published by a package spec, standalone units, and triggers._

```cypher
MATCH (spec:PackageSpec)-[:HAS_UNIT]->(u:DbProgramUnit)
RETURN u.packageName AS Package, u.name AS Unit, 'PUBLISHED' AS Kind
UNION
MATCH (u:DbProgramUnit {isStandalone: true})
RETURN '' AS Package, u.name AS Unit, 'STANDALONE' AS Kind
UNION
MATCH (t:DbTrigger)-[:FIRES_ON]->(tab:DbTable)
RETURN tab.name AS Package, t.name AS Unit, 'TRIGGER' AS Kind;
```

## Callers broken by a package spec change

_A spec change breaks every caller; the same change to a body does not. This is why the two are separate nodes._

```cypher
MATCH (p:DbPackage {name: $objectName})-[:HAS_SPEC]->(:PackageSpec)
      -[:HAS_UNIT]->(published:DbProgramUnit)
OPTIONAL MATCH (caller:DbProgramUnit)-[:CALLS]->(published)
RETURN published.name AS PublishedUnit,
       collect(DISTINCT caller.packageName + '.' + caller.name) AS Callers
ORDER BY PublishedUnit;
```

## Most depended-upon objects

_Where a change costs most. Sequence the migration around these._

```cypher
MATCH (n)<-[r:CALLS|READS_FROM|WRITES_TO|DEPENDS_ON]-()
WHERE n:DbTable OR n:DbView OR n:DbPackage OR n:DbProgramUnit
RETURN labels(n)[0] AS Type, n.name AS Name, count(r) AS Dependents
ORDER BY Dependents DESC
LIMIT 25;
```

## View lineage

_What a view is built from, through any depth of nesting._

```cypher
MATCH path = (v:DbView)-[:DEPENDS_ON*1..5]->(t:DbTable)
RETURN v.name AS View, t.name AS BaseTable, length(path) AS Depth
ORDER BY View, Depth;
```

## Everything that feeds a table

_Column-level provenance starts here: which statements write this table, and what they read to do it._

```cypher
MATCH (target:DbTable {name: $objectName})<-[:WRITES_TO]-(s:SqlStatement)
OPTIONAL MATCH (s)-[:READS_FROM]->(src:DbTable)
OPTIONAL MATCH (u:DbProgramUnit)-[:EXECUTES_SQL]->(s)
RETURN u.name AS Unit, s.verb AS Verb,
       collect(DISTINCT src.name) AS ReadsFrom
ORDER BY Unit;
```

## What touches a column

_The question a column rename or a type change starts with. Reports the statement and the unit that runs it; the graph does not claim which column feeds which._

```cypher
MATCH (c:DbColumn {name: $columnName})<-[:REFERENCES_COLUMN]-(s:SqlStatement)
OPTIONAL MATCH (u:DbProgramUnit)-[:EXECUTES_SQL]->(s)
RETURN c.tableName AS Table, c.name AS Column,
       collect(DISTINCT u.name) AS Units, s.verb AS Verb
ORDER BY Table, Column;
```

## Tables that are queried together

_Where a composite index or a denormalisation would pay. JOINS is only emitted when a statement combines more than one table, so a plain read never appears here._

```cypher
MATCH (s:SqlStatement)-[:JOINS]->(t:DbTable)
WITH s, collect(DISTINCT t.name) AS Tables
WHERE size(Tables) > 1
RETURN Tables, count(*) AS Statements
ORDER BY Statements DESC
LIMIT 25;
```

## What depends on a user-defined type

_A type change is a recompile for everything that declares it, and that dependency is invisible in the data-access edges._

```cypher
MATCH (dependent)-[:USES_TYPE]->(t:DbType)
RETURN t.name AS Type, t.typeCategory AS Category,
       collect(dependent.name) AS Dependents
ORDER BY Type;
```

## Business function down to the tables it changes

_The chain a modernisation conversation runs on: capability to code to data. Check `origin` before quoting it -- a derived seed is a starting point, a declared one is a fact._

```cypher
MATCH (d:BusinessDomain)<-[:PART_OF_DOMAIN]-(f:BusinessFunction)
      -[:IMPLEMENTED_BY]->(u:DbProgramUnit)
MATCH (u)-[:EXECUTES_SQL]->(:SqlStatement)-[:WRITES_TO]->(t:DbTable)
RETURN d.name AS Domain, f.name AS Function, f.origin AS Origin,
       f.confidence AS Confidence, u.name AS Unit,
       collect(DISTINCT t.name) AS Writes
ORDER BY Domain, Function;
```

## Entry points with no test

_Where a rewrite carries the most risk: callable from outside, changes data, and nothing covers it._

```cypher
MATCH (u:DbProgramUnit)
WHERE (u.isPublished OR u.isStandalone) AND NOT u.declaredOnly
  AND NOT (u)-[:HAS_TEST]->(:TestCase)
  AND (u)-[:EXECUTES_SQL]->(:SqlStatement)-[:WRITES_TO]->()
RETURN u.owner AS Schema, u.packageName AS Package,
       u.name AS Unit, u.complexity AS Complexity
ORDER BY Complexity DESC;
```

## What covers a program unit

_Read before changing a unit: the cases that exercise it, and the suite they live in._

```cypher
MATCH (u:DbProgramUnit)-[:HAS_TEST]->(c:TestCase)
RETURN u.packageName AS Package, u.name AS Unit,
       c.suite AS Suite, collect(c.displayName) AS Cases
ORDER BY Package, Unit;
```

## Triggers and what they fire on

_Hidden control flow: a write to a table may run code the caller never mentions._

```cypher
MATCH (t:DbTrigger)-[f:FIRES_ON]->(tab:DbTable)
RETURN tab.name AS Table, t.name AS Trigger,
       t.triggeringEvent AS Event, t.filePath AS File
ORDER BY Table, Trigger;
```

## Where dependency analysis stops

_Units that build SQL at runtime. Their dependencies are not in this graph and must not be assumed absent._

```cypher
MATCH (u:DbProgramUnit {hasDynamicSql: true})
RETURN u.packageName AS Package, u.name AS Unit,
       u.filePath AS File, u.lineStart AS Line
ORDER BY Package, Unit;
```

## Unresolved references

_Names the analysis saw but could not bind. Quote this alongside any completeness claim._

```cypher
MATCH (src)-[:UNRESOLVED]->(u:UnresolvedRef)
RETURN u.name AS Reference, u.kinds AS Kinds,
       count(src) AS ReferencedBy
ORDER BY ReferencedBy DESC;
```

## Findings by severity

_The rule catalogue output, most severe first._

```cypher
MATCH (target)-[:HAS_ISSUE]->(i:Issue)
OPTIONAL MATCH (i)-[:HAS_RECOMMENDATION]->(r:Recommendation)
RETURN i.severity AS Severity, i.ruleId AS Rule,
       i.targetName AS Target, i.description AS Finding,
       r.text AS Recommendation
ORDER BY CASE i.severity WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END, Rule;
```

## Units nothing calls

_Private body units with no caller in the analysed tree. Check the dynamic-SQL list before deleting any of them._

```cypher
MATCH (body:PackageBody)-[:HAS_UNIT]->(u:DbProgramUnit)
WHERE NOT ()-[:CALLS]->(u)
  AND NOT (:PackageSpec)-[:HAS_UNIT]->(u)
RETURN u.packageName AS Package, u.name AS Unit, u.loc AS Lines
ORDER BY Lines DESC;
```

## Complex code that changes often

_Where defects concentrate: high complexity plus high churn._

```cypher
MATCH (f:File)<-[:CHANGED]-(c:Commit)
WITH f, count(c) AS Churn
MATCH (f)-[:DEFINES]->()<-[:HAS_UNIT*0..1]-()
MATCH (u:DbProgramUnit) WHERE u.filePath = f.filePath
RETURN f.filePath AS File, Churn,
       round(sum(u.complexity)) AS TotalComplexity
ORDER BY Churn * TotalComplexity DESC
LIMIT 25;
```
