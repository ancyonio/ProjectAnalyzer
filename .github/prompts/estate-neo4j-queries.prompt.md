---
mode: agent
description: Load the federated estate graph into Neo4j and answer a cross-estate question with Cypher.
---

# Federated estate graph in Neo4j

Question: `${input:question:e.g. which APEX pages and TIBCO processes break if ORDERS changes?}`

## 1. Load, if it is not loaded

```bash
PYTHONPATH=tools python -m estate_analyzer -o analysis_output_estate federate \
  --tibco analysis_output --apex analysis_output_apex \
  --oracle analysis_output_oracle --estate-map estate_map.json
python scripts/push_to_neo4j.py -o analysis_output_estate
```

The push script creates the constraints, indexes and full-text indexes declared in
`analysis_output_estate/neo4j_indexes.json`. `--wipe` clears the whole database and is
almost never what you want on a shared instance.

**Load the federated graph into its own database**, with `-d estate` or a separate
instance. Its node ids are estate-namespaced (`tibco:act_0007`), so loading it
alongside a single-estate export produces two representations of the same artefact
under two ids. The `db:` family is the deliberate exception and will merge — which is
correct, and is exactly why the rest must not.

## 2. Know what is different about this graph

| Property | On every node | Meaning |
|---|---|---|
| `estate` | yes | `tibco`, `apex`, `oracle`, or `cross` for a federated finding |
| `estates` | merged nodes only | every contributing estate, semicolon separated |
| `sourceNodeId` | yes | the id the originating analyzer used |
| `:Federated` label | merged nodes only | contributed by more than one estate |

On relationships, an inferred cross-estate edge carries `basis`, `confidence`,
`origin` and `evidence` — the statement that justified it.

## 3. Start from the cookbook

`analysis_output_estate/ANALYSIS_QUERIES.md` holds the query set: node counts by
estate, shared database objects, contended tables, TIBCO-to-table access with its
confidence, end-to-end page-to-integration paths, cross-estate blast radius, every
inferred edge weakest-first, unmapped datasources, the `XE-` findings, the whole
ledger by estate, duplicate statements, and what each estate contributed. Take the
closest one and adapt it rather than writing from scratch.

Set the parameters first:

```cypher
:param objectName => 'ORDERS'
:param pageName   => 'Orders'
```

## 4. Write the query

- Traverse with named relationship types, never `-[*]-` unbounded.
- Bound the depth: `*1..4` is the practical ceiling for a page-to-integration chain.
- **Never traverse `CONTAINS_ESTATE`.** It is membership, not dependency; including it
  makes every artefact reachable from every other and destroys the signal. Exclude
  `BELONGS_TO`, `OWNS`, `DEFINES`, `CONTAINS_FILE`, `HAS_UNIT`, `HAS_METRIC` and
  `HAS_ISSUE` for the same reason.
- **Filter or report on `confidence`.** A query that returns an inferred edge without
  showing its basis presents a 0.5 guess and a 1.0 merge as the same fact. Either add
  `WHERE r.confidence >= 0.8`, or return `r.basis` in the result.
- Use the specific verb (`INSERTS_INTO`, `DELETES_FROM`) when the question is about
  provenance or retention, and the `WRITES_TO` roll-up only when any write will do.
- To ask "does this cross an estate boundary", compare the two ends:
  `WHERE a.estate <> b.estate`.

## 5. Report

The query, the result table, and one sentence on what it means.

State the bound explicitly. The result is a **lower bound** — say so in those words —
if any of these is true:

- `graph.meta.coverage.sqlBindCoverage` or `datasourceCoverage` is below 80 %
- any JDBC datasource is unmapped
- any activity in `links.json` under `unbound` reaches the schema in question
- any upstream estate is below its own coverage gate

A count from this graph is "what the join can resolve", never "what exists". And a
zero result is never evidence of absence for service, message or file coupling —
none of those are joined at all.
