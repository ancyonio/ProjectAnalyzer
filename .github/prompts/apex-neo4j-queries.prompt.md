---
mode: agent
description: Load the APEX graph into Neo4j and answer a question with Cypher.
---

# APEX graph in Neo4j

Question: `${input:question:e.g. which pages would break if ORDER_PKG.CREATE_ORDER changes?}`

## 1. Load, if it is not loaded

```bash
PYTHONPATH=tools python -m apex_analyzer -o analysis_output_apex analyze --source <export>
python scripts/push_to_neo4j.py -o analysis_output_apex --dataset <datasetId>
```

`--dataset` (the value of `graph.meta.datasetId`) removes only this application's
nodes before loading, leaving other applications and the shared database layer
intact. `--wipe` clears the whole database and is almost never what you want on a
shared instance.

The push script creates the constraints, indexes and full-text indexes declared in
`analysis_output_apex/neo4j_indexes.json`.

## 2. Start from the cookbook

`analysis_output_apex/ANALYSIS_QUERIES.md` holds the query set: impact, column
lineage, orphan detection, complexity, unsecured writes, duplicate SQL, release
impact, provenance audit. Take the closest one and adapt it rather than writing from
scratch.

## 3. Write the query

- Traverse with named relationship types, never `-[*]-` unbounded.
- Bound the depth (`*1..8` is the practical ceiling for page-to-database chains).
- Exclude `BELONGS_TO`, `DEFINES`, `HAS_ISSUE` from dependency traversals — they
  connect everything and destroy signal.
- Filter by `datasetId` when more than one application is loaded.

## 4. Report

The query, the result table, and one sentence on what it means. If any traversed edge
carries `resolution: 'dynamic'` or `'unresolved'`, say the result is a lower bound.
