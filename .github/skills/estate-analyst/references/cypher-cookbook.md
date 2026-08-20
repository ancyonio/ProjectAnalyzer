<!-- Generated from tools/estate_analyzer/graph/queries.py.
     Regenerate with:
       PYTHONPATH=tools python -c "from estate_analyzer.graph.queries import render_markdown; print(render_markdown())"
     Do not hand-edit: the analyzer emits the same cookbook into
     <output>/ANALYSIS_QUERIES.md, and the two must agree. -->
# Federated Estate Knowledge Graph — Cypher Query Cookbook

Every node carries an `estate` property (`tibco`, `apex`, `oracle`) and every node contributed by more than one estate carries `estates` and the `:Federated` label. Inferred cross-estate edges carry `basis` and `confidence`; filter on them rather than trusting every edge equally.

| id | Question |
|---|---|
| `node-counts-by-estate` | Node counts by estate and label (verification) |
| `shared-database-objects` | Database objects contributed by more than one estate |
| `contended-tables` | Tables written by more than one estate |
| `tibco-to-table` | Which TIBCO activity touches a database table |
| `end-to-end-path` | End to end: APEX page to the integration that feeds it |
| `blast-radius-across-estates` | Everything that breaks if a table changes, in every estate |
| `inferred-edges` | Every inferred cross-estate edge, weakest first |
| `unmapped-datasources` | JDBC resources with no schema mapping |
| `cross-estate-findings` | Findings that only exist across estates |
| `findings-by-estate` | The whole findings ledger, by estate |
| `duplicate-statements` | The same statement implemented in two estates |
| `estate-coverage` | What each estate contributed |

## Node counts by estate and label (verification)

_Confirm the import populated all three estates._

```cypher
MATCH (n)
WHERE n.estate IS NOT NULL
RETURN n.estate AS Estate, labels(n)[0] AS NodeType, count(n) AS Count
ORDER BY Estate, Count DESC;
```

## Database objects contributed by more than one estate

_The exact half of the join: these merged on natural key alone, with no heuristic._

```cypher
MATCH (n:Federated)
WHERE n.estates CONTAINS ";"
RETURN labels(n)[0] AS Label, n.name AS Name, n.estates AS Estates
ORDER BY Label, Name;
```

## Tables written by more than one estate

_The hardest thing in any cutover: two writers on two release trains. This is finding XE-001._

```cypher
MATCH (w)-[r:WRITES_TO|INSERTS_INTO|UPDATES|DELETES_FROM]->(t:DbTable)
WITH t, collect(DISTINCT w.estate) AS estates
WHERE size(estates) > 1
RETURN t.name AS Table, estates AS WrittenBy
ORDER BY size(estates) DESC, Table;
```

## Which TIBCO activity touches a database table

_The question the wrapper exists for. Confidence and basis come with the answer, because this edge is inferred._

```cypher
MATCH (p:BWProcess)-[:EXECUTES]->(a:Activity)-[r:READS_FROM|WRITES_TO|INSERTS_INTO|UPDATES|DELETES_FROM]->(t)
WHERE t.name = $objectName
RETURN p.name AS Process, a.name AS Activity, type(r) AS Access,
       r.basis AS Basis, r.confidence AS Confidence, r.evidence AS Sql
ORDER BY Process, Activity;
```

## End to end: APEX page to the integration that feeds it

_The full chain a change has to survive - user surface, data, integration - in one query._

```cypher
MATCH path = (page:ApexPage)-[*1..4]->(t:DbTable)<-[:WRITES_TO|INSERTS_INTO|UPDATES]-(a:Activity)
WHERE page.name = $pageName
RETURN page.name AS Page, t.name AS Table, a.name AS Activity,
       a.module AS TibcoModule
LIMIT 50;
```

## Everything that breaks if a table changes, in every estate

_A single-estate impact query answers a third of this._

```cypher
MATCH (t:DbTable {name: $objectName})<-[*1..4]-(n)
WHERE n.estate IS NOT NULL
RETURN DISTINCT n.estate AS Estate, labels(n)[0] AS Label, n.name AS Name
ORDER BY Estate, Label, Name;
```

## Every inferred cross-estate edge, weakest first

_Audit the join. Anything at confidence 0.5 is a bare-name match and should be confirmed by hand._

```cypher
MATCH (a)-[r]->(b)
WHERE r.origin = "inferred"
RETURN a.estate AS FromEstate, a.name AS From, type(r) AS Rel,
       b.name AS To, r.basis AS Basis, r.confidence AS Confidence
ORDER BY Confidence ASC, From;
```

## JDBC resources with no schema mapping

_Everything behind these is missing from the graph. This is finding XE-005._

```cypher
MATCH (r:SharedResource)
WHERE r.resourceType = "JDBC_CONNECTION"
  AND NOT (r)-[:CONNECTS_TO_SCHEMA]->()
RETURN r.name AS Resource, r.module AS Module, r.url AS Url;
```

## Findings that only exist across estates

_The XE- catalogue, with the recommendation attached._

```cypher
MATCH (i:Issue)-[:HAS_RECOMMENDATION]->(rec:Recommendation)
WHERE i.ruleId STARTS WITH "XE-"
RETURN i.ruleId AS Rule, i.severity AS Severity, i.targetName AS Target,
       i.description AS Finding, rec.text AS Recommendation
ORDER BY Severity DESC, Rule;
```

## The whole findings ledger, by estate

_Rule ids are namespaced (APEX.SEC-001, ORA.SEC-001, XE-001) because the same ordinal means different things in different dialects._

```cypher
MATCH (i:Issue)
RETURN i.estate AS Estate, i.category AS Category, i.severity AS Severity,
       count(i) AS Count
ORDER BY Estate, Category, Severity DESC;
```

## The same statement implemented in two estates

_Content-addressed nodes keep their digest, so a duplicate is visible rather than merged away. Finding XE-004._

```cypher
MATCH (s)
WHERE s.sourceNodeId STARTS WITH "sql:" OR s.sourceNodeId STARTS WITH "plsql:"
WITH s.sourceNodeId AS Digest, collect(DISTINCT s.estate) AS estates
WHERE size(estates) > 1
RETURN Digest, estates AS Estates;
```

## What each estate contributed

_Quote the weakest input, never an average, when stating how complete a federated answer is._

```cypher
MATCH (e:Estate)-[:CONTAINS_ESTATE]->(root)
RETURN e.name AS Estate, e.title AS Title, e.estateNodes AS Nodes,
       e.sourceRoot AS SourceRoot, collect(root.name) AS Roots
ORDER BY Estate;
```
