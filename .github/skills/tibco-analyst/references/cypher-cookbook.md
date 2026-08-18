# Neo4j workflow and Cypher cookbook

The analyzer answers every question below in-memory, so Neo4j is optional. Load the
graph when a team wants to explore interactively, join the graph to other data, or
re-verify a published finding independently.

The canonical cookbook ships with each run as `<output>/analysis_queries.cypher`
(runnable) and `<output>/ANALYSIS_QUERIES.md` (readable). `queries` regenerates both
without re-parsing. This reference explains what each query is for and what a
correct answer looks like.

## Importing

### Option 1 — admin import from CSV (large estates, empty database)

`analyze` writes an admin-import compatible pair. Columns are typed:
`nodeId:ID`, `label:LABEL`, `name`, then one column per property observed in the
graph (`complexityScore:float`, `activityCount:int`, `required:boolean`, and so on);
relationships use `:START_ID`, `:END_ID`, `:TYPE` plus edge properties.

```bash
neo4j-admin database import full \
  --nodes=neo4j_nodes.csv \
  --relationships=neo4j_relationships.csv \
  --database=tibco-migration --overwrite-destination
```

This creates the database offline and is the fastest route. It destroys any existing
content in the target database — use a dedicated database name.

### Option 2 — the generated Cypher script (small estates, existing database)

```bash
cypher-shell -u neo4j -p <password> -d tibco-migration -f neo4j_import.cypher
```

`neo4j_import.cypher` creates a uniqueness constraint on `nodeId` per label plus
indexes on `name`, `BWProcess.module`, `BWProcess.tier`, `Activity.category`,
`XSD.namespace`, `SharedResource.resourceType` and `GlobalVariable.module`, then
`CREATE`s every node and relationship. It matches relationship endpoints by the
`nodeId` property, so the constraints must exist first — do not reorder the file.
It is also pasteable into Neo4j Browser for small graphs.

Whichever route you take, run the two verification queries below before trusting a
single analysis result.

## Verification queries

### Node counts by label
*Purpose: confirm the import populated every expected label.*

```cypher
MATCH (n)
RETURN labels(n)[0] AS NodeType, count(n) AS Count
ORDER BY Count DESC;
```

**Expected shape:** one row per label, descending. Compare the totals against
`context/project-facts.md` — they must match exactly. A missing label means a failed
or partial import, not a finding about the estate.

### Relationship counts by type
*Purpose: confirm every semantic edge type survived the import.*

```cypher
MATCH ()-[r]->()
RETURN type(r) AS RelationshipType, count(r) AS Count
ORDER BY Count DESC;
```

**Expected shape:** one row per relationship type. `BELONGS_TO`, `EXECUTES` and
`CONTAINS` must be present; their absence is the same condition `validate` reports
as an ERROR.

### Orphan check
*Purpose: find nodes with no edges at all — usually an import defect, occasionally a
real finding.*

```cypher
MATCH (n)
WHERE NOT (n)--()
RETURN labels(n)[0] AS Type, n.name AS Name, n.filePath AS File
ORDER BY Type, Name;
```

**Expected shape:** empty, or only `System`, `GlobalVariable`, `DataTransformation`,
`AESchema` and `ExternalReference` rows — the labels `validate` tolerates as
disconnected. Any orphan `BWProcess` or `Activity` means the import lost edges.

### Entry point catalogue
*Purpose: list every externally reachable surface.*

```cypher
MATCH (p:BWProcess)
WHERE p.entryType IS NOT NULL AND p.entryType <> 'NONE'
RETURN p.name AS Process, p.entryType AS EntryType, p.endpoint AS Endpoint,
       p.module AS Module, p.complexityScore AS Complexity
ORDER BY p.entryType, p.complexityScore DESC;
```

**Expected shape:** one row per entry point, grouped by type. Row count must equal
the table in `context/entry-points.md`. Zero rows on a real estate means the starter
elements were not parsed — investigate before reporting "no entry points".

## Analysis queries

### Migration complexity ranking
*Purpose: order the migration backlog by measured complexity.*

```cypher
MATCH (p:BWProcess)
OPTIONAL MATCH (p)-[:EXECUTES]->(a:Activity)
OPTIONAL MATCH (p)-[:USES_XSD]->(x:XSD)
OPTIONAL MATCH (p)-[:HANDLES_ERROR]->(e:ErrorHandler)
RETURN p.name AS Process, p.tier AS Tier, p.complexityScore AS Score,
       count(DISTINCT a) AS Activities, count(DISTINCT x) AS Schemas,
       count(DISTINCT e) AS ErrorHandlers
ORDER BY Score DESC;
```

**Expected shape:** every process, descending by score, tiers clustering at the top.
The head of this list is where senior design effort goes.

### Blast radius of a schema change
*Purpose: which artefacts break if this XSD changes.*

```cypher
:param schemaName => "CreditResponse"

MATCH (x:XSD {name: $schemaName})<-[:USES_XSD|IMPORTS_SCHEMA*1..3]-(dependent)
RETURN DISTINCT labels(dependent)[0] AS Type, dependent.name AS Name,
       dependent.module AS Module, dependent.entryType AS EntryType
ORDER BY Type, Name;
```

**Expected shape:** a mixed list of `BWProcess`, `Service` and `XSD` rows. Rows with
a non-null `EntryType` are the externally visible regressions — quote those first.
This is the contract-only view; the CLI's `impact` walks every edge type and adds
weighting, hop counts and test scope.

### Field-level blast radius
*Purpose: which processes touch one specific element.*

```cypher
:param fieldName => "creditScore"

MATCH (e:Element {name: $fieldName})<-[:CONTAINS]-(x:XSD)<-[:USES_XSD]-(p:BWProcess)
RETURN DISTINCT p.name AS Process, p.module AS Module, x.name AS Schema,
       e.javaType AS JavaType, e.required AS Required;
```

**Expected shape:** one row per consuming process. An empty result means the field
name is wrong or the element is defined inline within a complex type rather than as a
named element — check `context/data-contracts.md` before concluding nothing uses it.

### Entry points affected by a process change
*Purpose: walk callers upward to the surfaces a regression becomes visible on.*

```cypher
:param processName => "ScoreCalculationProcess"

MATCH (target:BWProcess {name: $processName})
MATCH path = (entry:BWProcess)-[:EXECUTES|CALLS*1..8]->(target)
WHERE entry.entryType IS NOT NULL AND entry.entryType <> 'NONE'
RETURN DISTINCT entry.name AS EntryPoint, entry.entryType AS Type,
       entry.endpoint AS Endpoint, length(path) AS Hops
ORDER BY Hops;
```

**Expected shape:** the entry points, nearest first. The path alternates `EXECUTES`
(process to its calling activity) and `CALLS` (activity to callee), so hop counts are
roughly twice the number of process-to-process hops.

### Circular process dependencies
*Purpose: cycles must be broken before incremental migration.*

```cypher
MATCH path = (p:BWProcess)-[:EXECUTES|CALLS*2..10]->(p)
RETURN DISTINCT [n IN nodes(path) WHERE n:BWProcess | n.name] AS Cycle
LIMIT 50;
```

**Expected shape:** ideally empty. Each returned list is a migration blocker: the
processes in it cannot be moved independently and must be resequenced or refactored.
Cross-check against `context/complexity.md`, which lists the same cycles.

### Orphan schemas (dead code)
*Purpose: XSDs nothing references — candidates to drop from scope.*

```cypher
MATCH (x:XSD)
WHERE NOT ()-[:USES_XSD|IMPORTS_SCHEMA]->(x)
RETURN x.name AS OrphanSchema, x.folder AS Location, x.namespace AS Namespace
ORDER BY x.name;
```

**Expected shape:** a short list on a healthy estate. Never present these as
deletable without the caveat that a consumer may live outside the scanned tree.

### Unreachable processes (dead code)
*Purpose: no caller and no entry point, so nothing can invoke them.*

```cypher
MATCH (p:BWProcess)
WHERE NOT ()-[:CALLS]->(p)
  AND (p.entryType IS NULL OR p.entryType = 'NONE')
RETURN p.name AS DeadProcess, p.module AS Module, p.folder AS Location
ORDER BY p.module;
```

**Expected shape:** a small list. Check each against `ExternalReference` nodes: a
process may be invoked from a project that was not scanned.

### Change hotspots
*Purpose: high in-degree means high blast radius per unit of change.*

```cypher
MATCH (n)<-[r]-()
WHERE n:XSD OR n:BWProcess OR n:SharedResource OR n:GlobalVariable
RETURN labels(n)[0] AS Type, n.name AS Name, count(r) AS Dependents
ORDER BY Dependents DESC
LIMIT 25;
```

**Expected shape:** shared schemas and utility sub-processes at the top. These are
the artefacts to freeze early and migrate carefully, and the natural targets for a
full `impact` run.

### External system touchpoints
*Purpose: every outbound integration that needs a Spring client.*

```cypher
MATCH (r:SharedResource)-[:CONNECTS_TO]->(s:System)
OPTIONAL MATCH (p:BWProcess)-[:REFERENCES]->(r)
RETURN s.name AS System, s.technology AS Technology, r.name AS Resource,
       collect(DISTINCT p.name) AS UsedByProcesses;
```

**Expected shape:** one row per resource. Note that in the graph `CONNECTS_TO`
originates from the synthetic `Adapter` node, so on some estates this query returns
nothing while the adapter form does:

```cypher
MATCH (a:Adapter)-[:CONNECTS_TO]->(s:System)
MATCH (a)-[:CONFIGURED_BY]->(r:SharedResource)
OPTIONAL MATCH (p:BWProcess)-[:REFERENCES]->(r)
RETURN s.name AS System, s.technology AS Technology, r.name AS Resource,
       r.host AS Host, r.url AS Url, collect(DISTINCT p.name) AS UsedByProcesses;
```

Prefer the adapter form; keep the first as a fallback for graphs where resources
connect directly.

### Processes without error handling
*Purpose: fault-handling gaps to close during migration.*

```cypher
MATCH (p:BWProcess)
WHERE NOT (p)-[:HANDLES_ERROR]->() AND p.activityCount > 3
RETURN p.name AS Process, p.module AS Module, p.activityCount AS Activities,
       p.tier AS Tier
ORDER BY p.activityCount DESC;
```

**Expected shape:** the processes whose failure behaviour is currently implicit. In
the target service each of these needs an explicit decision: retry, dead-letter,
compensate or fail fast. Entry-point processes in this list are the highest priority.

### Global variable usage
*Purpose: the configuration surface to externalise into `application.yml`.*

```cypher
MATCH (g:GlobalVariable)
OPTIONAL MATCH (p:BWProcess)-[:CONFIGURED_BY]->(g)
RETURN g.name AS Variable, g.value AS DefaultValue, g.module AS Module,
       count(p) AS UsedBy
ORDER BY UsedBy DESC, g.name;
```

**Expected shape:** every variable, most-used first. `UsedBy = 0` means no `%%Var%%`
reference was found in any process file — it may still be consumed by a deployment
descriptor, so treat zero as "not referenced in process XML", not "unused". Values
containing password, secret, credential or key are masked at parse time.

### Activity mix by Spring target
*Purpose: sizing — how much of each Spring construct the migration needs.*

```cypher
MATCH (a:Activity)
RETURN a.category AS Category, a.springEquivalent AS SpringTarget, count(*) AS Count
ORDER BY Count DESC;
```

**Expected shape:** a distribution. Rows with `SpringTarget = 'Manual Implementation'`
(category `CUSTOM`) are the unmapped activities that need design attention; quote
their count explicitly rather than folding them into a total.

### Data lineage, process to field
*Purpose: trace which fields a given process actually touches.*

```cypher
MATCH (p:BWProcess {name: $processName})-[:USES_XSD]->(x:XSD)-[:CONTAINS]->(e:Element)
RETURN x.name AS Schema, x.namespace AS Namespace,
       collect({field: e.name, javaType: e.javaType, required: e.required}) AS Fields;
```

**Expected shape:** one row per schema used. This is schema-level reachability, not
runtime data flow — the process may touch only a subset of the listed fields. Say so
when quoting it.

## Using query results in a finding

A Cypher result is evidence only when it is reproducible. Quote the query, the
parameter values, and the database it ran against, then the rows. If a Cypher result
disagrees with the context packs, the import is stale — re-run `analyze` and
re-import rather than choosing the more convenient number.
