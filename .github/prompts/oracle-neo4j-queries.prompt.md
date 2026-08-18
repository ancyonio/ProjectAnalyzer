---
mode: agent
description: Load the Oracle PL/SQL graph into Neo4j and answer a question with Cypher.
---

# Oracle graph in Neo4j

Question: `${input:question:e.g. which program units would break if ORDERS changes?}`

## 1. Load, if it is not loaded

```bash
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle analyze \
  --source <repo_root> --schema <OWNER>
python scripts/push_to_neo4j.py -o analysis_output_oracle
```

The push script creates the constraints, indexes and full-text indexes declared in
`analysis_output_oracle/neo4j_indexes.json`. `--wipe` clears the whole database and is
almost never what you want on a shared instance.

Ids are natural keys, so a re-load is idempotent: the same source produces the same
node ids and merges cleanly over a previous load.

## 2. Start from the cookbook

`analysis_output_oracle/ANALYSIS_QUERIES.md` holds the query set: writers of a table,
the exact access verbs, blast radius, call chains, entry points, spec-change impact,
hotspots, view and table lineage, triggers, dynamic-SQL sites, unresolved references,
findings, dead code and churn-versus-complexity. Take the closest one and adapt it
rather than writing from scratch.

Set the parameters first:

```cypher
:param objectName => 'ORDERS'
:param unitName   => 'CREATE_CUSTOMER'
```

## 3. Write the query

- Traverse with named relationship types, never `-[*]-` unbounded.
- Bound the depth: `*1..6` is the practical ceiling for a caller-to-table chain.
- **Never traverse `HAS_UNIT` in a dependency query.** Package membership is
  structure, not a call path; including it makes every unit in a package look
  reachable from any other and destroys the signal.
- Exclude `OWNS`, `DEFINES`, `CONTAINS_FILE`, `HAS_METRIC` and `HAS_ISSUE` from
  dependency traversals for the same reason.
- Use the specific verb (`INSERTS_INTO`, `DELETES_FROM`) when the question is about
  provenance or retention, and the `WRITES_TO` roll-up only when any write will do.

## 4. Report

The query, the result table, and one sentence on what it means.

State the bound explicitly. If any unit on a traversed path carries
`hasDynamicSql: true`, or if `graph.meta.coverage.callResolution` is below 80 %, the
result is a **lower bound** — say so. A count from this graph is "what the analyzer
can resolve", never "what exists".
