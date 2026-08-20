---
name: estate-analyst
description: Answer questions that span more than one estate — TIBCO BusinessWorks, Oracle APEX and Oracle PL/SQL together — with this repository's read-only federation wrapper. Use when asked which integration writes the table an APEX page reports over, what a schema change breaks across all three estates, which tables have more than one writer, where two estates duplicate the same logic, what the end-to-end blast radius of a change is, or in what order a mixed estate should be modernised. Also use when a single-estate answer looks suspiciously self-contained and the real dependency may live in another estate.
---

# Cross-estate analysis

## What this skill is for

Questions whose answer does not fit inside one estate. The three analyzers each
produce a complete graph of their own world; `tools/estate_analyzer` joins those
three finished graphs and answers what none of them can alone.

| Layer | What it does | Who owns it |
|---|---|---|
| 1 — deterministic | `tools/estate_analyzer` federates the three `graph.json` files, adds cross-estate edges with a declared confidence, raises the `XE-` findings, and derives the modernisation sequence | The Python CLI |
| 2 — narrative | Explains what the join means, and what it could not join | You |

Use it for: shared and contended data, end-to-end blast radius, integration-to-page
dependency, duplicate logic across estates, transaction-boundary conflicts, and
cutover sequencing.

Do not use it for a question one estate can answer. "How many APEX pages are
there" is `apex-analyst`; "what does this BW process do" is `tibco-analyst`;
"which unit writes ORDERS" *within Oracle* is `oracle-analyst`. Reaching for the
wrapper when one analyzer would do produces a slower answer with more caveats
attached to it.

## The rule that is not negotiable

**The wrapper joins facts; it does not produce them.**

1. `federate` reads three finished graphs. If any of them is missing, stale or
   failed its own validation, the federated answer inherits that — say so, and
   name the estate.
2. Never state a cross-estate dependency without its `basis` and `confidence`.
   `exact` needed no heuristic. `name` is a bare-name guess at confidence 0.5 and
   must be confirmed by hand before anyone acts on it.
3. **Quote `sqlBindCoverage` and `datasourceCoverage` before any completeness
   claim.** Below 80 % the cross-estate view is provisional. Below either gate,
   "no integration touches this table" is not a finding you can make.
4. **Never conclude that a table has one writer without checking the unbound
   list.** An activity behind an unmapped datasource, or one that builds SQL at
   runtime, is invisible by design — that is recorded in `links.json`, not hidden.
5. The federated graph is not more complete than its weakest input. Quote the
   weakest estate's own coverage, never an average.

## Invocation

From the repository root (Python 3.9+, no third-party packages needed):

```bash
# no install
PYTHONPATH=tools python -m estate_analyzer -o analysis_output_estate <subcommand>

# installed
pip install -e . && estate-analyze -o analysis_output_estate <subcommand>
```

Before answering any cross-estate question, the three estates must already be
analysed, and then:

```bash
PYTHONPATH=tools python -m estate_analyzer -o analysis_output_estate federate \
    --tibco analysis_output --apex analysis_output_apex \
    --oracle analysis_output_oracle --estate-map estate_map.json
PYTHONPATH=tools python -m estate_analyzer -o analysis_output_estate validate
PYTHONPATH=tools python -m estate_analyzer -o analysis_output_estate context
```

`federate` is the only command that reads the upstream graphs, and it is
read-only: it parses no source and writes nothing into their output directories.
Everything else reads `analysis_output_estate/graph.json`.

Subcommands: `federate`, `validate`, `links`, `inventory`, `findings`, `impact`,
`sequence`, `diagrams`, `context`, `report`, `queries`, `all`. Full
specification: [README.md](../../../README.md#cross-estate-analysis).

## The estate map

A JDBC url names a *database*, not an Oracle *schema*, so the wrapper never
infers the mapping. Without `--estate-map`, every JDBC datasource is reported
unmapped and everything behind it is missing from the graph. If the operator has
not supplied one, say that first — it is usually the single biggest gap in the
answer.

```json
{ "datasources": [
    { "resource": "sync.OrderApp_JDBCConnectionResource", "schema": "ORDER_APP" }
] }
```

## Where the answers already are

| Question | Route |
|---|---|
| What did the join actually produce, and at what confidence? | `links`, or `context/cross-estate-links.md` |
| Which data does more than one estate touch? | `context/shared-data.md` |
| Which tables have more than one writer? | `inventory`, contended tables — or finding `XE-001` |
| What breaks across all three estates if X changes? | `impact --target "DbTable:ORDERS" --direction upstream` |
| In what order should this be modernised? | `sequence`, or `context/sequence.md` |
| What could the join *not* do? | `context/unresolved.md` — read this before any negative claim |
| The whole findings ledger | `findings`, or `context/findings.md` |

## Reading the findings ledger

Rule ids are namespaced because the dialects reuse ordinals for different rules:

| Prefix | Meaning |
|---|---|
| `TIB.` | raised by the TIBCO analyzer, reproduced unchanged |
| `APEX.` | raised by the APEX analyzer, reproduced unchanged |
| `ORA.` | raised by the Oracle analyzer, reproduced unchanged |
| `XE-` | exists only across estates; the wrapper raised it |

`APEX.SEC-001` is SQL injection through dynamic SQL. `ORA.SEC-001` is dynamic SQL
that defeats static resolution. They are different rules. Never quote a bare
`SEC-001`.

The cross-estate catalogue:

| Rule | Fires when |
|---|---|
| `XE-001` | a table is written by more than one estate |
| `XE-002` | a TIBCO statement names a table no database estate models |
| `XE-003` | a table written from TIBCO is also written by Oracle code that commits |
| `XE-004` | the same statement digest appears in two estates |
| `XE-005` | a JDBC shared resource has no estate-map entry |
| `XE-006` | a JDBC activity carries no static SQL |
| `XE-007` | an APEX page reads a table a TIBCO process writes |

## How to write the answer

State the join before the conclusion. A cross-estate claim that does not say
which half of the join it rests on is not checkable:

> `ORDER_LINES` is written by two estates: the APEX package `ORDER_PKG.CANCEL_ORDER`
> (exact — both database estates name the same object) and the TIBCO activity
> `CustomerSync.WriteOrderLines` (qualified-name, confidence 0.8, via the mapped
> `sync.OrderApp_JDBCConnectionResource` datasource). Two pages report over it.
> SQL bind coverage is 60 %, so there may be further writers behind the one
> unmapped datasource and the one activity that builds SQL at runtime.

Style: British-neutral professional English, no emoji, no hype, tables over prose
when carrying more than three facts, uncertainty stated plainly with the command
that would remove it.
