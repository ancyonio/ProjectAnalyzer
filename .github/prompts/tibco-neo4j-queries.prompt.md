---
mode: agent
description: Load the exported knowledge graph into Neo4j, verify the import against the analyzer's own counts, then run the Cypher cookbook and report the results as tables.
tools: ['codebase', 'terminal']
---

# Neo4j: load, verify and query the TIBCO graph

Move the graph into Neo4j so the estate can be queried interactively, prove the import is
complete, then work through the analysis cookbook.

**Database name:** `${input:database:tibco-migration}`

## Preconditions

```bash
ls -1 ${input:outputDir:analysis_output}/neo4j_nodes.csv \
      ${input:outputDir:analysis_output}/neo4j_relationships.csv \
      ${input:outputDir:analysis_output}/neo4j_import.cypher \
      ${input:outputDir:analysis_output}/analysis_queries.cypher
PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} validate
```

Do not import a graph whose validation status is FAIL — quote the failing rules and stop.

Record the analyzer's own counts before importing; they are the expected results.

```bash
PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} \
  queries --print-queries | head -40
sed -n '1,10p' ${input:outputDir:analysis_output}/neo4j_import.cypher
```

The header comment of `neo4j_import.cypher` states the node count, relationship count, labels
and relationship types. Those are the numbers the import must reproduce.

## Procedure

1. **Choose an import route.**

   **Route A — Cypher script** (works against a running database, including Neo4j Aura and
   Desktop; no restart needed):

   ```bash
   cypher-shell -u neo4j -p <password> -d ${input:database:tibco-migration} \
     -f ${input:outputDir:analysis_output}/neo4j_import.cypher
   ```

   The script creates uniqueness constraints on `nodeId` and name indexes per label before
   inserting, so it is safe to re-run.

   **Route B — bulk admin import** (fastest, requires a stopped database and overwrites it):

   ```bash
   neo4j-admin database import full \
     --nodes=${input:outputDir:analysis_output}/neo4j_nodes.csv \
     --relationships=${input:outputDir:analysis_output}/neo4j_relationships.csv \
     --database=${input:database:tibco-migration} --overwrite-destination
   ```

   In Neo4j Browser, `:play` is not needed — paste the contents of `neo4j_import.cypher`
   directly, or use `:source`.

2. **Verify the import. Do not proceed until both counts match.**

   ```cypher
   MATCH (n) RETURN labels(n)[0] AS NodeType, count(n) AS Count ORDER BY Count DESC;
   MATCH ()-[r]->() RETURN type(r) AS RelationshipType, count(r) AS Count ORDER BY Count DESC;
   ```

   Compare, row by row, with `context/project-facts.md` ("Nodes by label", "Relationships by
   type") and with the `neo4j_import.cypher` header. Report the comparison as a table with a
   Match column; a single mismatched row means the import is incomplete, and the fix is to
   re-import, not to explain the difference away.

   Two more integrity checks:

   ```cypher
   MATCH (n) WHERE n.nodeId IS NULL RETURN count(n) AS NodesWithoutId;
   MATCH (n) WHERE NOT (n)--() RETURN labels(n)[0] AS Label, count(n) AS Isolated ORDER BY Isolated DESC;
   ```

   Isolated nodes are expected only for System, GlobalVariable, DataTransformation, AESchema and
   ExternalReference. Anything else isolated is a finding.

3. **Run the cookbook.** Every query is in
   `${input:outputDir:analysis_output}/analysis_queries.cypher`, and documented with its purpose
   in `ANALYSIS_QUERIES.md`. Run them in this order and capture each result set:

   | Id | Question |
   |---|---|
   | `node-counts` | Node counts by label (verification) |
   | `rel-counts` | Relationship counts by type (verification) |
   | `entry-points` | Entry point catalogue |
   | `complexity-ranking` | Migration complexity ranking |
   | `schema-blast-radius` | Which processes break if a given XSD changes |
   | `field-blast-radius` | Which processes touch a given element |
   | `reachable-entry-points` | Entry points affected by a change to a given process |
   | `circular-dependencies` | Cycles that block incremental migration |
   | `orphan-schemas` | Schemas with no consumer |
   | `unreachable-processes` | Processes with no caller and no entry point |
   | `shared-hotspots` | Most-reused artefacts |
   | `external-systems` | External system touchpoints |
   | `error-coverage` | Processes without error handling |
   | `global-variable-usage` | Global variables destined for `application.yml` |
   | `activity-mix` | Activity mix by Spring Boot target |

4. **Supply the parameters.** Four queries are parameterised — `$schemaName`, `$fieldName`,
   `$processName`. Take real values from the graph, never invented ones:

   ```cypher
   :param schemaName => '${input:schemaName:CreditResponse}';
   :param fieldName  => '${input:fieldName:customerId}';
   :param processName => '${input:processName:MainCreditProcess}';
   ```

   Confirm each value exists first:

   ```bash
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} \
     search "${input:schemaName:CreditResponse}" --label XSD --top 5
   ```

5. **Cross-check two Cypher results against the local engine.** The analyzer answers the same
   questions in memory, so disagreement means the import is wrong:

   ```bash
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} \
     impact --target "XSD:${input:schemaName:CreditResponse}" --depth 3
   ```

   The impacted-artefact set should match `schema-blast-radius` for the same schema, and the
   affected entry points should match `reachable-entry-points`. The `impact` report also prints
   an equivalent Cypher query — run it and compare directly.

6. **Report every result as a Markdown table**, one section per query, with the query id, its
   purpose, the Cypher run (including parameter values), the row count, and the rows. Truncate
   long result sets at 25 rows and say how many were omitted.

## Acceptance criteria

- Node and relationship counts in Neo4j match `context/project-facts.md` exactly, shown as a
  comparison table.
- Every cookbook query has been run, or is explicitly listed as skipped with a reason.
- All parameter values were confirmed to exist in the graph before use.
- At least one cross-check against the local `impact` engine is reported.
- Interpretation is separated from results — the tables come first, the reading follows.

## Do not

- Do not write Cypher that mutates the graph (`CREATE`, `MERGE`, `SET`, `DELETE`) beyond the
  generated import script.
- Do not adjust a cookbook query to make its result look tidier; report the result as it comes.
- Do not explain away a count mismatch — re-import.
- Do not invent parameter values or query a schema, field or process you have not confirmed.
- Do not report Neo4j results as more authoritative than `graph.json`; they are the same data,
  and a disagreement is an import defect.
