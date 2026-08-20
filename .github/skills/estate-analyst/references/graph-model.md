# The federated graph model

Three finished graphs in, one graph out. `estate-analyze federate` reads
`graph.json` from each estate's output directory and nothing else — it never parses
source, never re-derives a fact an analyzer already computed, and never writes into
an estate's output directory.

Everything below follows from one decision: **which ids merge and which are kept
apart.**

## The two halves of the join

| Id family | Namespaced? | Why |
|---|---|---|
| `db:…` | **No** | Two estates naming `db:ORDER_APP.ORDERS` mean the same table. This is the only intentional merge in the design. |
| `sql:…` `plsql:…` `js:…` | **Yes** | Content-addressed. Merging them would hide `XE-004`, which exists precisely to compare their digests across estates. |
| everything else | **Yes** — `tibco:`, `apex:`, `oracle:` | Two estates numbering an activity `act_0007` mean different things. |

So APEX and Oracle need no matcher at all. They share `analyzer_core.ids`, so the
moment the graphs are unioned, `db:ORDER_APP.ORDERS` **is** one node — an APEX page
and an Oracle procedure hang off the same table without anything being inferred.

TIBCO shares no ids with either. Every TIBCO edge into the database estate is
**inferred**, and this is the single most important fact about this graph.

## Inferred edges carry their own evidence

Each cross-estate link records `origin`, `basis`, `confidence` and `evidence`:

| `basis` | Confidence | Means | On by default |
|---|---|---|---|
| `exact` | 1.0 | schema-qualified name matched a modelled object | yes |
| `declared` | 0.9 | the estate map said so | yes |
| `qualified-name` | 0.8 | owner and name both matched | yes |
| `name` | 0.5 | bare table name matched, owner unknown | **no** — `--allow-name-match` |

`name` matching is off by default on purpose. In an estate with `ORDERS` in three
schemas it produces confident-looking nonsense. Turning it on is a decision to
accept noise in exchange for reach, and an answer built on it must say so.

**Never quote an inferred edge as fact without its confidence.** Check
`context/cross-estate-links.md`, or run the `inferred-edges` query, which orders them
weakest first for exactly this reason.

## Node properties after a merge

A node contributed by more than one estate gains the `:Federated` label, an `estates`
list, and keeps `sourceNodeId`. Properties that describe an estate's *view* of a
shared object are **not** merged:

```
origin, fanIn, fanOut, filePath, sourceFile, lineStart, lineEnd,
confidence, datasetId
```

Each estate measured its own graph and its own files, so both values are correct and
flattening them into one would be a fiction. When you need one of these for a shared
table, say which estate's view you are quoting.

Secondary labels in play: `:Federated` (contributed by ≥2 estates), `:DbObject`,
`:Unresolved`.

## What is here that is nowhere else

The federated vocabulary is large — 82 labels, 81 relationship types — because it is
the union of three. Almost all of it is documented in the source skills
([tibco](../../tibco-analyst/references/graph-model.md),
[apex](../../apex-analyst/references/graph-model.md),
[oracle](../../oracle-analyst/references/graph-model.md)). Read those for anything
estate-specific.

Only three things are genuinely new at this level, and they are the only reasons to
be in this graph rather than one of the three:

| Question | Path |
|---|---|
| Which tables does more than one estate write? | `(t:DbTable)<-[:WRITES_TO]-()` grouped by `estate` — rule `XE-001` |
| What feeds this APEX page from outside APEX? | `(:ApexPage)-[…]->(t:DbTable)<-[:WRITES_TO]-(:Activity)` — rule `XE-007` |
| What breaks in *every* estate if this table changes? | `impact --target "DbTable:ORDERS" --direction upstream` |

If a question can be answered inside one estate's graph, answer it there. The
federated graph is bigger, its cross-estate edges are weaker, and using it for a
single-estate question buys nothing and costs confidence.

## Findings are namespaced; rule ids alone are ambiguous

The merged ledger carries all four catalogues. Source-estate findings are prefixed
`TIB.`, `APEX.`, `ORA.`; cross-estate findings are `XE-` with
`category: CROSS_ESTATE`.

`SEC-001` means a credential in a shared resource (TIBCO), dynamic SQL (Oracle), and
something else again in APEX. **An unqualified rule id in a cross-estate answer is
ambiguous at best and wrong at worst.** See
[rule-catalogue.md](rule-catalogue.md).

## Reading coverage

The federation has its own coverage contract, separate from the three it consumes,
and it fails in ways they cannot see:

- **`datasource-coverage`** — JDBC resources with no estate-map entry. A JDBC url
  names a database, not a schema, so this cannot be inferred. Every table behind an
  unmapped datasource is absent from lineage and from every blast radius.
- **`sql-bind-coverage`** — how much TIBCO SQL bound to a modelled object. Low means
  the cross-estate view is provisional.

Both gate at 80%. Read `context/unresolved.md` **before making any negative claim** —
"no other estate writes this table" is only true if no unmapped datasource and no
runtime-SQL activity could have.

An estate's own coverage figures still apply underneath: a federated answer is at
best as complete as the weakest of the three graphs it was built from.
