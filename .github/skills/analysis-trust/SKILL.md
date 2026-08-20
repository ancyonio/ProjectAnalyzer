---
name: analysis-trust
description: Read the coverage, provenance and confidence signals that every analyzer in this repository emits — use when asked how complete or how reliable an analysis is, before making any claim that something does not exist, when deciding whether a graph is fit to answer a question, when a finding rests on an inferred or derived node, or when reconciling answers that disagree between the TIBCO, APEX, Oracle and federated graphs.
---

# Reading the analysis with the right amount of trust

Every analyzer here emits a graph **and** a statement about what that graph does not
know. The second part is not a caveat section — it is the thing that makes the first
part safe to use. This skill is how to read it.

One rule underpins all four analyzers: *where a fact cannot be established it is
recorded as a gap, never quietly dropped.* A missing edge and a deliberately-recorded
gap look identical in a node count, and only one of them is honest.

## The three questions, in order

They must be asked in this order, because **each is measured over what the previous
one produced.**

| # | Question | Signal |
|---|---|---|
| 1 | Did the parser read the code? | `parseQuality`, `statementsPartial`, `statementsFailed`, `ddlUnparsed` |
| 2 | Did the names it found bind to objects? | `resolutionCoverage`, `UnresolvedRef` |
| 3 | Did the call and data edges resolve? | `callResolution`, `dynamicSqlSites` |

Asking them out of order produces the single most dangerous artefact this toolkit can
generate: **a graph reporting 100% resolution that read a third of its code.** Every
name the parser managed to extract bound perfectly; the rest was never seen. The
Oracle analyzer states parse quality before resolution in its context banner for
exactly this reason — see
[oracle-analyst/references/resolution-limits.md](../oracle-analyst/references/resolution-limits.md).

## Provenance: how a node came to exist

Read `origin` before quoting any node or edge.

| `origin` | Means | Trust |
|---|---|---|
| `ddl` / parsed | read from a file in the tree | a statement about the **repository** |
| `dictionary` | from a data-dictionary extract | a statement about the **deployed database**, authoritative |
| `inferred` | created because something referenced it | exists; its properties may not |
| `derived` | the analyzer's own reasoning, with `confidence` and `evidence` | a starting point, not a finding |
| `declared` | stated in an input map, `confidence` 1.0 | a fact, and it wins over `derived` |

Two consequences worth stating in answers:

- **`dictionaryAvailable: false` means you are describing source control, not
  production.** They disagree in real estates — an object dropped in production but
  still committed, a column added by a hotfix that never came back — and the
  disagreement is itself a finding.
- **A `derived` node is not evidence.** The Oracle and APEX business layers seed
  `BusinessDomain` / `BusinessFunction` at confidence 0.4–0.5 from package grouping
  and writes. Quoting one as though a stakeholder had said it is the fastest way to
  lose an audience.

## Confidence on cross-estate edges

APEX and Oracle share `analyzer_core.ids`, so a table they both touch is one node
with nothing inferred. **TIBCO shares no ids with either**, so every TIBCO edge into
the database is inferred and carries `basis` and `confidence`:

| `basis` | Confidence | On by default |
|---|---|---|
| `exact` | 1.0 | yes |
| `declared` | 0.9 | yes |
| `qualified-name` | 0.8 | yes |
| `name` | 0.5 | **no** — `--allow-name-match` |

Bare-name matching is off by default because in an estate with `ORDERS` in three
schemas it produces confident-looking nonsense. If it is on, say so.

## Before any negative claim

"Nothing writes this table", "this procedure is dead", "no other estate touches
this" — every one of these is a claim about **absence**, and absence is exactly what a
static analysis is worst at. Check all four before saying it:

1. **Dynamic / runtime SQL** — `dynamicSqlSites`, Oracle `SEC-001`, estate `XE-006`.
   Dependency analysis provably stops there; a "dead" object may be reached from
   precisely there.
2. **Unresolved references** — `context/unresolved.md`. Each is a dependency the graph
   knows exists and cannot follow.
3. **Unmapped datasources** — estate `XE-005`. A JDBC url names a database, not a
   schema, so it cannot be inferred, and everything behind an unmapped one is dark.
4. **Scope of the scan** — a unit called from an external job, ORDS, a scheduler or a
   module outside the analysed tree is indistinguishable from a dead one here.

The honest form is almost never "nothing does X". It is **"nothing that this analysis
can resolve does X, and here is what it could not resolve."**

## Where the numbers live

```bash
# each analyzer prints its own coverage block after `analyze`
oracle-analyze -o analysis_output_oracle validate     # exit 2 = gate failed
tibco-analyze  -o analysis_output        validate
apex-analyze   -o analysis_output_apex   validate
estate-analyze -o analysis_output_estate validate
```

- `graph.json` → `meta.coverage` — the machine-readable contract
- `validation_report.md` / `.json` — the gates, with `INFO` / `WARNING` / `ERROR`
- `context/*.md` — every pack opens with a coverage banner; `context/unresolved.md`
  is the one to read before a negative claim
- `context/estate-facts.md` — the banner an agent should quote from

Gates in force: resolution and call resolution warn below **80%**, Oracle parse
quality below **90%**, estate datasource and SQL-bind coverage below **80%**.

## When two estates disagree

They are usually both right about different things. A shared `DbTable` keeps
per-estate values for `origin`, `fanIn`, `fanOut`, `filePath`, `lineStart`, `lineEnd`
and `confidence` — each estate measured its own graph, and merging them into one
number would be a fiction. Say which estate's view you are quoting.

## How to say it

Put the limit next to the claim, not in a footnote, and name the command that would
remove it:

> Four procedures write `ORDERS`. Resolution is 96% over 100% of the code parsed, so
> this is complete for the analysed tree — but `ARCHIVE_ORDERS` builds SQL at runtime
> and one JDBC datasource is unmapped, so there may be writers this cannot see.
> Supplying `--db-meta` and mapping `sync.OrderApp_JDBCConnectionResource` in the
> estate map would close both gaps.

Never present a coverage figure as a quality score for the estate. It measures the
**analysis**, not the code.
