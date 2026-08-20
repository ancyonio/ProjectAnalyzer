# ProjectAnalyzer

**A deterministic analysis toolkit for legacy estates — TIBCO BusinessWorks, Oracle
APEX, Oracle PL/SQL, and the three of them joined into one graph.**

It answers, with evidence rather than inference: what is in this estate, what depends on
what, what breaks if I change this, what is dead, what is untested, and in what order it
should be modernised.

## The one design decision everything follows from

The toolkit is split across a boundary that is never crossed:

| Layer | Responsibility | Implementation |
|-------|----------------|----------------|
| **1 — Deterministic** | Extract *facts*: artefacts, dependencies, complexity, entry points, dead code, lineage, blast radius | Four Python analyzers over a shared core, standard library only |
| **2 — LLM** | Explain, prioritise and write up those facts | GitHub Copilot: instructions, skills, prompt files and chat modes |

**Counts, dependency edges and impact radii are never produced by a language model.** They
are parsed from the source tree, exported to CSV/Cypher/JSON, and checked by a built-in
validation gate. Copilot reads that output and does what it is genuinely good at:
interpretation, prioritisation and narrative.

The corollary matters as much as the rule: where a fact cannot be established it is
**recorded as a gap**, never quietly dropped. A missing edge and a deliberately-recorded
gap look identical in a node count, and only one of them is honest.

## The four analyzers

| Analyzer | Command | Estate | Graph |
|---|---|---|---|
| `tools/tibco_analyzer` | `tibco-analyze` | BW5 (`.process`) and BW6 / BWCE (`.bwp`) | 19 labels, 20 edge types |
| `tools/apex_analyzer` | `apex-analyze` | Oracle APEX applications | 56 labels, 55 edge types |
| `tools/oracle_analyzer` | `oracle-analyze` | Oracle PL/SQL in a repository | 32 labels, 37 edge types |
| `tools/estate_analyzer` | `estate-analyze` | **all three, federated** | 82 labels, 81 edge types |

The two Oracle analyzers share one database vocabulary — `DbTable`, `READS_FROM`,
`HAS_UNIT` mean the same thing in both graphs — so the same Cypher answers either, and a
table they both touch becomes one node the moment the graphs are unioned.

`estate-analyze` is a **read-only wrapper**: it parses no source, imports nothing from the
three analyzers, and writes nothing into their output directories. It reads their
`graph.json` and nothing else.

---

## Contents

- [Quick start](#quick-start)
- [Features](#features)
- [Current implementation](#current-implementation)
- [What it answers](#what-it-answers)
- [Oracle APEX analysis](#oracle-apex-analysis)
- [Cross-estate analysis](#cross-estate-analysis)
- [Preparing your source tree](#preparing-your-source-tree)
- [Command reference](#command-reference)
- [The knowledge graph](#the-knowledge-graph)
- [Neo4j](#neo4j)
- [How semantic search works](#how-semantic-search-works)
- [How blast radius works](#how-blast-radius-works)
- [Verifying a run](#verifying-a-run)
- [Tuning it to your estate](#tuning-it-to-your-estate)
- [Wiring the gates into CI](#wiring-the-gates-into-ci)
- [Using it with GitHub Copilot](#using-it-with-github-copilot)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Extending it](#extending-it)

---

## Quick start

```bash
git clone <this-repo> && cd <repo>
pip install -e .                     # or: export PYTHONPATH=tools
```

Requires **Python 3.9+ and no third-party packages**. Optional extras:
`pip install -e ".[embeddings]"` (local vectors), `".[openai]"`, `".[neo4j]"`.

Then run whichever analyzer matches your estate. `all` runs the whole pipeline in
order — parse, validate, diagrams, context packs, report scaffolds, Cypher cookbook:

```bash
# TIBCO BusinessWorks (BW5 and/or BW6)
tibco-analyze  -o analysis_output        all --source /path/to/tibco_code

# Oracle APEX  (--db-meta is optional but strongly recommended)
apex-analyze   -o analysis_output_apex   all --source /path/to/apex_export

# Oracle PL/SQL in a repository
oracle-analyze -o analysis_output_oracle all --source /path/to/plsql --schema APP_OWNER
```

Each writes `graph.json`, the Neo4j export, `reports/`, `context/` and
`generated_diagrams/` into its output directory, and prints a coverage block. **Read
that block before reading anything else** — it says what the graph does not know.

Once two or more estates are analysed, join them:

```bash
estate-analyze -o analysis_output_estate all \
  --tibco analysis_output --apex analysis_output_apex --oracle analysis_output_oracle
```

Then open the `reports/` directory, and in VS Code run the matching Copilot prompt —
`/tibco-bootstrap-analysis`, `/apex-bootstrap-analysis`, `/oracle-bootstrap-analysis`
or `/estate-bootstrap-analysis` — to fill the `<!-- LLM: … -->` narrative sections.

Without installing, every command works as
`PYTHONPATH=tools python -m <tibco|apex|oracle|estate>_analyzer -o <dir> <subcommand>`.

### Check it worked

```bash
oracle-analyze -o analysis_output_oracle validate     # exit 0 ok, 2 gate failed
```

`validate` is the gate. It exits 2 when the graph is too provisional to build on, which
is what makes it usable in CI — see [Wiring the gates into CI](#wiring-the-gates-into-ci).

---

## Features

### Extraction

- **Four source dialects** — BW5 and BW6 process XML, APEX `wwv_flow_api` exports, Oracle
  DDL and PL/SQL, plus an optional Oracle data-dictionary extract that is treated as
  authoritative where present.
- **Package structure that reflects change semantics** — an Oracle package is three nodes
  (`DbPackage`, `PackageSpec`, `PackageBody`) because a spec change breaks every caller and
  the same change to a body does not. Collapsing them makes the most useful impact question
  unanswerable.
- **Semantic data access, not a generic `USES`** — `READS_FROM`, `INSERTS_INTO`, `UPDATES`,
  `DELETES_FROM`, plus a `WRITES_TO` roll-up, so "which procedures *modify* this table" is
  one query.
- **Column and join awareness** — `REFERENCES_COLUMN` binds a statement to the columns it
  names; `JOINS` records which tables are queried together.
- **Git provenance** — commits, authors and per-file churn, correct whether the analysed
  root is the repository root or a subdirectory of it.

### Analysis

- **Weighted blast radius** — not just reachability: per-edge weights, label multipliers,
  entry-point bonuses, a risk band and the regression test scope. Structural edges are
  deliberately excluded, so one procedure's change does not implicate its whole package.
- **Data lineage** — what feeds a table and what it feeds, through statements, views,
  triggers and synonyms.
- **Modernisation sequencing** — cutover waves derived from one rule: *a component may not
  be cut over before the data it shares has an owner.*
- **Rule catalogues** — deterministic security, correctness, performance and
  technical-debt findings, each an `:Issue` node with a linked `:Recommendation`.
- **Hybrid semantic search** (TIBCO) — BM25 with optional local or API embeddings.
- **Business and test layers** (Oracle) — `BusinessDomain` / `BusinessFunction` seeded from
  package grouping and writes, and `TestCase` built from utPLSQL annotations, so "what is
  this for" and "what proves it still works" become graph questions.

### Honesty

- **A coverage contract on every run** — parse quality, resolution coverage, call
  resolution, dynamic-SQL sites, unparsed DDL, and for the federation, datasource and
  SQL-bind coverage.
- **Provenance on every node** — `origin` distinguishes parsed from dictionary-sourced from
  inferred from derived from declared, with `confidence` where it is not certain.
- **Gates that fail the build** — `validate` exits 2 below threshold, so a provisional graph
  cannot silently become a delivered report.
- **Unresolvable references become nodes** — `UnresolvedRef` and `ExternalReference` make the
  edge of the analysis visible instead of absent.

### Delivery

- **Neo4j export** — admin-import CSV pair, a runnable Cypher script and an index sidecar;
  `scripts/push_to_neo4j.py` loads it over Bolt.
- **Cypher cookbooks** — 67 curated queries across the four analyzers, each with its
  purpose, emitted alongside the graph and mirrored into the skill references.
- **Diagrams** — Mermaid and offline-safe PlantUML generated from the parsed graph, so
  nothing in a diagram is invented.
- **Context packs** — budgeted, coverage-banner-first Markdown for grounding an LLM.
- **Report scaffolds** — generated tables with `<!-- LLM: … -->` slots for the narrative.

---

## Current implementation

Production-ready for all four estates. **129 tests pass**; ~24,500 lines of Python with
**zero required runtime dependencies**, so it runs on an air-gapped build agent.

| Capability | TIBCO | APEX | Oracle | Estate |
|---|:--:|:--:|:--:|:--:|
| Parse → graph → Neo4j export | ✅ | ✅ | ✅ | ✅ |
| Validation gate (CI exit 2) | ✅ | ✅ | ✅ | ✅ |
| Rule catalogue | ✅ | ✅ | ✅ | ✅ |
| Weighted blast radius | ✅ | ✅ | ✅ | ✅ |
| Diagrams · context packs · reports | ✅ | ✅ | ✅ | ✅ |
| Coverage contract | ✅ | ✅ | ✅ | ✅ |
| Git provenance | — | ✅ | ✅ | — |
| Data lineage | — | — | ✅ | ✅ |
| Column-level references | — | ✅ | ✅ | — |
| Business layer | — | ✅ | ✅ | — |
| Test layer (utPLSQL) | — | — | ✅ | — |
| Parse-quality reporting | — | — | ✅ | — |
| Semantic search | ✅ | — | — | — |
| Cutover sequencing | ✅ | — | — | ✅ |

**Copilot assets:** 6 skills with 19 reference guides, 22 prompt files, 12 chat modes and
4 path-scoped instruction files.

### Known limits — stated, not hidden

- **Column-to-column flow is not modelled.** `REFERENCES_COLUMN` records that a statement
  *names* a column, not that one column populates another.
- **Dynamic SQL is where dependency analysis stops.** It is flagged (`SEC-001`,
  `dynamicSqlSites`) rather than guessed at. A "dead" object may be reached from exactly
  there.
- **Local variables, cursors and user-defined exceptions are not nodes.** Modelling every
  local declaration inflates node count by an order of magnitude and buries the structure
  that matters.
- **Business rules are not extracted.** A `CHECK` constraint encodes one, but recovering it
  means interpreting the expression, and this toolkit does not interpret.
- **TIBCO shares no ids with the database estates**, so every TIBCO-to-database edge is
  inferred and carries `basis` and `confidence`. Bare-name matching is off by default.
- **The parsers are pattern-based, not grammar-based.** A deliberate trade for zero
  dependencies and honest degradation; `parseQuality` and `ddlUnparsed` exist so you can
  tell when it stops being the right trade.

---

## What it answers

**Any estate**

1. **What is in it?** — full inventory, complexity ranking, entry-point catalogue, dead
   code, and the artefacts that carry the most dependencies.
2. **What does it look like?** — Mermaid and PlantUML diagrams generated from the parsed
   graph, so nothing in a diagram is invented.
3. **What breaks if I change X?** — weighted blast-radius traversal naming the affected
   entry points, the risk band and the exact regression test scope.
4. **What is wrong with it?** — deterministic security, correctness, performance and
   technical-debt findings, each traceable to a file and a line.
5. **How much of this can I trust?** — a coverage contract on every run, and a gate that
   fails the build when the graph is too provisional to build on.

**Per estate**

6. **Where is functionality X implemented?** (TIBCO) — hybrid semantic search over
   processes, activities, schemas, transformations, SQL, JMS destinations and endpoints.
7. **Where does this data come from and go?** (Oracle) — table and statement-level lineage
   through views, triggers and synonyms.
8. **What is this code *for*, and what proves it still works?** (Oracle, APEX) — a business
   layer seeded from structure and writes, and a test layer built from utPLSQL annotations.

**Across all three at once**

9. **Which integration writes the table this APEX page reports over?** — and every other
   question that needs two estates joined.
10. **In what order should a mixed estate be cut over?** — derived migration waves, plus
    what must be decided before any of it means anything.

---

## Oracle APEX analysis

The APEX analyzer builds a deterministic graph of applications, pages, regions, items,
processes, shared components, SQL and PL/SQL, and the database objects they use. It supports
split SQL exports (preferred), single-file exports, schema DDL committed alongside the
application, and an optional database dictionary extract. Readable YAML exports are detected
but are not parsed; use an SQL export instead. Both `wwv_flow_api.*` (APEX 21.1 and earlier)
and `wwv_flow_imp*.*` (21.2 and later) are supported.

### APEX quick start

```bash
# Optional but strongly recommended: extract deployed database metadata
sql> @tools/apex_analyzer/extract/run_all.sql 100 ORDER_APP
python tools/apex_analyzer/extract/merge_parts.py db_meta_parts.json db_meta.json

# Run the complete pipeline over a split or single-file SQL export
PYTHONPATH=tools python -m apex_analyzer -o analysis_output_apex all \
  --source ./f100 --db-meta db_meta.json

# Installed equivalent
pip install -e .
apex-analyze -o analysis_output_apex all --source ./f100 --db-meta db_meta.json
```

### APEX commands

```text
apex-analyze analyze   --source <export_root> [--app-id 100] [--schema ORDER_APP]
                       [--db-meta db_meta.json] [--apex-meta apex_meta.json]
                       [--git] [--git-range v1.2..HEAD]
apex-analyze validate  [--strict]
apex-analyze rules     [--category SECURITY] [--min-severity HIGH] [--fail-on CRITICAL]
apex-analyze impact    --target "DbTable:ORDERS" [--direction upstream|downstream|both]
                       [--depth 8] [--fail-on HIGH] [--save <path stem>]
apex-analyze diagrams  [--format mermaid|plantuml|both]
apex-analyze context | report | queries
apex-analyze diff      --baseline <older graph.json>
apex-analyze all       --source <export_root>
```

Exit codes are `0` for success, `1` for usage or runtime errors, and `2` for a gate
failure. `analysis_output_apex/` contains `graph.json`, Neo4j CSV/Cypher and index metadata,
the query cookbook, analysis summary, validation reports, context packs, report scaffolds,
and generated Mermaid and PlantUML diagrams. Every command after `analyze` reads the graph,
not the APEX export.

### APEX coverage and validation

`graph.meta.coverage.resolutionCoverage` is the share of SQL references resolved to modelled
database objects. Below 80% the `AX-COVERAGE` gate warns and the graph is provisional.
Unresolved references remain explicit `DbObject:Unresolved` nodes rather than disappearing.
The validator also checks id grammar and uniqueness, relationship endpoints, vocabulary,
containment, property types, provenance, unhandled export procedures, dependency mismatches,
and unexpected orphan nodes. A FAIL means the graph is not trustworthy.

The database layer can come from committed DDL or `--db-meta`; dictionary data outranks DDL
because it describes the deployed database. Inferred edges carry a confidence and resolution
basis. The analyzer has no live Oracle dependency, and APEX does not currently expose TIBCO's
`search` or `index` commands.

Verify APEX or shared SQL-binder changes with:

```bash
python tests/test_apex_analyzer.py
python tests/test_sql_binder.py
```

The agent workflow lives in `.github/skills/apex-analyst/`, with the `apex-analyst`,
`apex-impact`, and `apex-diagrammer` chat modes and the `/apex-bootstrap-analysis`,
`/apex-impact-analysis`, `/apex-security-review`, and `/apex-neo4j-queries` prompts.

---

## Cross-estate analysis

The three analyzers each produce a complete graph of their own world. `estate-analyze`
joins those three finished graphs and answers what none of them can alone.

```bash
# 1. Analyse each estate as usual
PYTHONPATH=tools python -m tibco_analyzer  -o analysis_output        analyze --source <tibco_root>
PYTHONPATH=tools python -m apex_analyzer   -o analysis_output_apex   analyze --source <export_root>
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle analyze --source <repo_root> --schema ORDER_APP

# 2. Join them. This reads their graph.json and nothing else.
PYTHONPATH=tools python -m estate_analyzer -o analysis_output_estate all     --tibco analysis_output --apex analysis_output_apex     --oracle analysis_output_oracle --estate-map estate_map.json
```

### The two halves of the join

**APEX and Oracle join exactly.** Both use the natural-key id grammar in
`analyzer_core.ids`, so `db:ORDER_APP.ORDERS` is the same id in both graphs and the two
views of one table become one node. No matcher, no heuristic, no confidence score. On the
committed fixtures, 24 nodes merge this way.

**TIBCO joins by inference.** It shares no ids with either database estate, so its edges
are matched from the SQL the parser already extracted (`sqlTables`, `sqlVerb`) plus the
JDBC resource behind the activity. Every one of those edges carries `origin`, `basis`,
`confidence` and the statement it came from:

| Basis | Confidence | Meaning |
|---|---|---|
| `exact` | 1.0 | the two graphs used the same natural key |
| `declared` | 0.9 | the operator mapped this datasource in the estate map |
| `qualified-name` | 0.8 | `owner.name` matched, the owner coming from the SQL or the mapped datasource |
| `name` | 0.5 | a bare table name matched exactly one object in one schema |

`name` matches are **suppressed by default**. They are computed, counted and listed, and
enter the graph only under `--allow-name-match`. A bare name matching two schemas is
rejected whatever the flag says.

Every non-database node id is prefixed by its estate (`tibco:`, `apex:`, or `oracle:`).
Only natural-key `db:` ids remain unchanged so APEX and Oracle views of the same object can
merge. Content-addressed `sql:`, `plsql:`, and `js:` nodes stay namespaced because merging
them would hide duplicated statements. Merged database nodes record all contributing estates;
property conflicts are retained with their resolution, while estate-specific measurements
are kept as `<property>ByEstate` values.

### The estate map

A JDBC url names a *database*, not an Oracle *schema*, so the wrapper never guesses it:

```json
{ "datasources": [
    { "resource": "sync.OrderApp_JDBCConnectionResource", "schema": "ORDER_APP",
      "note": "orders-db.internal:1521/ORDERS is served by the ORDER_APP schema" }
] }
```

An unmapped datasource is not an error — it is finding `XE-005`, and everything behind it
lands in the unbound list where it can be seen.

### Its own coverage gates

| Metric | Definition | Gate |
|---|---|---|
| `sqlBindCoverage` | JDBC activities carrying static SQL that resolved to a database object | 80 % |
| `datasourceCoverage` | JDBC resources with an estate-map entry | 80 % |
| `mergedDbNodes` | nodes contributed by more than one estate | reported |
| `crossEstateLinks` | inferred edges added, by basis | reported |

Below either gate the federated graph is **provisional** and every answer drawn from it
must say so. Activities that build SQL at runtime are excluded from the denominator and
counted separately, so a blind spot is reported as a blind spot rather than as a low
score.

### What it finds that no single analyzer can

| Rule | Fires when |
|---|---|
| `XE-001` | a table is written by more than one estate |
| `XE-002` | a TIBCO statement names a table no database estate models |
| `XE-003` | a table written from TIBCO is also written by Oracle code that commits |
| `XE-004` | the same statement digest appears in two estates |
| `XE-005` | a JDBC shared resource has no estate-map entry |
| `XE-006` | a JDBC activity carries no static SQL |
| `XE-007` | an APEX page reads a table a TIBCO process writes |

Imported findings are namespaced on the way in, because the dialects reuse ordinals for
different rules: `APEX.SEC-001` is SQL injection through dynamic SQL, `ORA.SEC-001` is
dynamic SQL that defeats static resolution. Categories are canonicalised too, so APEX
`TECH_DEBT` and Oracle `DEBT` are one category in the merged ledger.

The federated vocabulary is the union of all three dialects plus `Estate`,
`CONTAINS_ESTATE`, and `CONNECTS_TO_SCHEMA`. Cross-estate data access deliberately reuses
`READS_FROM`, `INSERTS_INTO`, `UPDATES`, `DELETES_FROM`, and `WRITES_TO`, so one query works
across all contributors.

### Worked examples

```bash
# Everything that breaks if a table changes — in all three estates at once
estate-analyze -o analysis_output_estate impact --target "DbTable:ORDERS" --direction upstream

# Every cross-estate edge, with the evidence for it, so a reviewer can reject one
estate-analyze -o analysis_output_estate links

# Only the links that rest on a guess
estate-analyze -o analysis_output_estate links --basis name

# The derived cutover order
estate-analyze -o analysis_output_estate sequence

# The merged ledger, cross-estate findings only
estate-analyze -o analysis_output_estate findings --category CROSS_ESTATE

# CI gate: the federated graph must be trustworthy before anything is built on it
estate-analyze -o analysis_output_estate validate --strict
```

`federate` is the only command that reads upstream graphs. The full command surface is
`federate`, `validate`, `links`, `inventory`, `findings`, `impact`, `sequence`, `diagrams`,
`context`, `report`, `queries`, and `all`; exit codes follow the same `0`/`1`/`2` contract.

### Output

`analysis_output_estate/` carries `graph.json`, `links.json` (every link, every suppressed
match, every unbound reference and every datasource), the Neo4j export, `context/` packs —
including `unresolved.md`, which states plainly what the join could not do — three report
scaffolds and three Mermaid diagrams.

---

## Preparing your source tree

Export the BW projects **without flattening folders** — the folder structure carries module
membership, which the analyzer uses to assign every artefact to a module:

```
tibco_code/
  CreditApp.module/
    Processes/  Schemas/  Service Descriptors/  Resources/  defaultVars.substvar
  CustomerCore.module/
    ...
```

Place it outside this repository (or inside, git-ignored) and pass the path with `--source`.
The first path segment under the source root becomes the module name, so exporting a single
module without its parent folder will collapse everything into one module.

---

## Command reference

All commands accept the global options `-o/--output DIR` (default `analysis_output`) and
`-v/--verbose`. Exit codes: `0` success, `1` usage or runtime error, `2` gate failure
(`validate` FAIL, `validate --strict` on WARN, `impact --fail-on` threshold reached).

| Command | Purpose | Key outputs |
|---------|---------|-------------|
| `analyze --source <dir>` | Parse the estate into a knowledge graph | `graph.json`, `neo4j_nodes.csv`, `neo4j_relationships.csv`, `neo4j_import.cypher`, `analysis_summary.json` |
| `validate [--strict]` | Referential integrity + completeness gate (exit 2 on FAIL; with `--strict`, also on WARN) | `validation_report.md/.json` |
| `index [--no-embeddings] [--provider …]` | Build the search index | `search_index/` |
| `search "<question>"` | Locate functionality; supports `--label`, `--module`, `--top`, `--json` | ranked hits with graph context |
| `impact --target "<Label>:<Name>"` | Blast radius; `--direction`, `--depth`, `--fail-on` | impact report `.md/.json/.mmd` |
| `diagrams [--format both]` | Architecture diagrams | `generated_diagrams/mermaid/…`, `…/plantuml/…` |
| `context` | LLM grounding packs | `context/*.md`, `context/processes/*.md`, `facts.json` |
| `report` | Step 00/01/02 report scaffolds with `<!-- LLM: … -->` slots | `reports/*.md`, `inventory.json` |
| `queries` | Cypher cookbook | `analysis_queries.cypher`, `ANALYSIS_QUERIES.md` |
| `all --source <dir>` | The whole pipeline | all of the above |

### `analyze --source <dir>`

The only command that reads the TIBCO source; everything else reads `<output>/graph.json`.

| Artefact | Parsed into |
|----------|-------------|
| `*.process` (BW5) | `BWProcess`, `Activity`, `Group`, `ErrorHandler`, `TRANSITIONS_TO`, sub-process `CALLS` |
| `*.bwp` (BW6/BWCE) | The same labels, parsed from BPEL: `extensionActivity` + native `receive`/`reply`/`invoke`, `link` and `sequence` control flow, `faultHandlers`, `scope`/`flow` groups |
| `*.xsd` | `XSD`, `Element`, `ComplexType`, `IMPORTS_SCHEMA` |
| `*.aeschema` | `AESchema` |
| `*.wsdl` | `Service`, `Operation`, `EXPOSES`, schema imports |
| shared resources, BW5 (`.sharedhttp`, `.sharedjdbc`, `.sharedjmscon`, `.id`, …) | `SharedResource`, `Adapter`, `System`, `REFERENCES`, `CONNECTS_TO` |
| shared resources, BW6/BWCE (`.jdbcResource`, `.jmsConnResource`, `.httpConnResource`, `.httpClientResource`, `.smtpResource`, …) | the same labels, read from the XMI `jndi:namedResource` envelope; a process is linked to the resource its `sca-bpel:sharedResourceType` property binds. Credentials are never copied into the graph |
| `*.substvar` | `GlobalVariable` (sensitive values masked) |
| `*.xsl`, `*.xslt` | `DataTransformation` |

Also writes `analysis_queries.cypher` and `ANALYSIS_QUERIES.md`.

### Coverage facts

`graph.meta.coverage` records how much of the source tree actually reached the graph, so a
small graph can be told apart from a partly-parsed one:

| Field | Meaning |
|---|---|
| `filesDiscovered` | Files found under `--source` |
| `filesModelled` | Files that produced at least one node |
| `filesSupported` | Files whose extensions are direct analyzer inputs |
| `filesSupportedModelled` | Supported files that produced at least one node |
| `artifactCoverage` | `filesSupportedModelled / filesSupported`; parser completeness |
| `estateFileCoverage` | `filesModelled / filesDiscovered`; total estate scope |
| `filesClassified` | Files matching a known artifact family |
| `unmodelledExtensions` | What the remainder is made of, largest first |
| `unmodelledSupportedExtensions` | Supported inputs that did not produce nodes |

Quote `artifactCoverage` and `estateFileCoverage` before making an inventory or completeness
claim. Low artifact coverage indicates a parser gap. Low estate-file coverage can be expected
when Java sources, policies and build metadata are present but outside the graph model.

### `validate [--strict]`

Runs the integrity gate: node-id uniqueness, referential integrity (graph and CSV), required
relationship-type coverage, process completeness, orphan detection, schema wiring,
entry-point presence, unresolved references. Writes `validation_report.md` and `.json`.
`--strict` also fails on warnings.

### `rules [--category C] [--rule ID] [--module M] [--min-severity S] [--fail-on S] [--json]`

Reads the rule findings back out of the graph. The rules themselves run as the last step of
`analyze`, so a finding travels in `graph.json` as an `Issue` with a `Recommendation` — the
same shape the APEX and Oracle catalogues use, which is what lets the cross-estate wrapper
merge all three ledgers.

| Rule | Fires when |
|---|---|
| `SEC-001` | a shared resource carries a credential inline (the `#!` obfuscation is reversible) |
| `SEC-002` | a secret-named global variable ships with a default value |
| `SEC-003` | a resource is pinned to a developer host |
| `CORR-001` | a process calls outside the engine with no error handler |
| `CORR-002` | a process has no starter and no caller, so nothing can invoke it |
| `PERF-001` | a JDBC activity selects every column |
| `DEBT-001` | a process is neither called nor exposed |
| `DEBT-002` | a shared resource nothing references |
| `DEBT-003` | a referenced artefact was not found in the scanned tree |

Credential *values* are never copied into the graph: the parser records only that one is
present. `--fail-on HIGH` exits 2, for CI.

### `index [--no-embeddings] [--provider auto|sentence-transformers|openai|azure-openai] [--source DIR]`

Builds the search index in `<output>/search_index/`. BM25 is always built. Vectors are added
only when a provider is available; the command reports which mode it used. `--source`
re-reads the TIBCO tree for richer document text (defaults to the analysed root).

### `search "<question>" [--top N] [--label L] [--module M] [--json] [--save PATH]`

Hybrid retrieval. `--label` and `--module` are repeatable. Each hit reports the file path,
node id, matched terms, and the graph neighbourhood (schemas used, callers, Spring targets).

### `impact --target REF [...]`

`REF` may be a node id (`xsd_0003`), a name (`CreditResponse`), a `Label:Name` pair
(`XSD:CreditResponse`), or a file path. Ambiguous references are reported rather than
guessed; pass `--label`, a node id, or `--all-matches`.

| Option | Meaning |
|--------|---------|
| `--depth N` | Maximum hops (default 4) |
| `--direction upstream\|downstream\|both` | Who depends on it / what it depends on / both |
| `--include-rel T`, `--exclude-rel T` | Restrict traversal to or from relationship types |
| `--fail-on NONE\|MEDIUM\|HIGH\|CRITICAL` | Exit 2 when the risk band reaches this level |
| `--save STEM` | Write `STEM.md`, `STEM.json` and `STEM.mmd` |

### `diagrams [--format mermaid|plantuml|both] [--diagram-dir DIR]`

Generates system context, module container, component, process dependency, schema usage,
canonical ER, integration surface, per-process flowcharts (Mermaid) and C4-style context /
container / component, deployment topology and per-process sequence diagrams (PlantUML).
PlantUML output uses no themes and no remote includes, so it renders offline.

### `context`

Writes the LLM grounding packs to `<output>/context/`: `project-facts.md`,
`entry-points.md`, `complexity.md`, `dead-code.md`, `integration-surface.md`,
`data-contracts.md`, `migration-sequence.md`, `processes/<Name>.md`, `facts.json`,
`MANIFEST.md`.

### `report [--reports-dir DIR]`

Scaffolds `Step00_TIBCO_ANALYSIS_REPORT.md`, `Step01_ARCHITECTURE_DIAGRAMS_REPORT.md` and
`Step02_DISCOVER_AND_BASELINE_REPORT.md` with every table filled from the graph, and
`<!-- LLM: … -->` markers where narrative is required. Also writes `inventory.json`.

### `queries [--print-queries]`

Writes (and optionally prints) the Cypher cookbook.

### `all --source <dir>`

`analyze` → `validate` → `index` → `diagrams` → `context` → `report`. Returns the validation
exit code, so a broken graph fails the pipeline.

### Worked examples

```bash
# Where is credit scoring implemented?
tibco-analyze search "where is the credit score calculated and published" --top 8

# Narrow to processes in one module
tibco-analyze search "nightly archive of decisions" --label BWProcess --module CreditApp.module

# What breaks if this schema changes?
tibco-analyze impact --target "XSD:CreditResponse" --depth 4 --save analysis_output/impact/credit-response

# What must be in scope to migrate this process?
tibco-analyze impact --target "BWProcess:MainCreditProcess" --direction downstream

# CI gate: fail the build on a critical-radius change
tibco-analyze impact --target "XSD:Common" --fail-on CRITICAL
```

---

## The knowledge graph

17 node labels and 17 relationship types, all derived from parsed XML:

```
(Module)
  └─[:BELONGS_TO]─(BWProcess)
        ├─[:EXECUTES {order}]─────>(Activity)─[:TRANSITIONS_TO {conditionType, condition}]─>(Activity)
        ├─[:USES_XSD]────────────>(XSD)─[:CONTAINS]─>(Element | ComplexType)
        ├─[:USES_WSDL]───────────>(Service)─[:EXPOSES]─>(Operation)
        ├─[:REFERENCES]──────────>(SharedResource)─[:CONNECTS_TO]─>(System)
        ├─[:CONFIGURED_BY]───────>(GlobalVariable)
        └─[:HANDLES_ERROR]───────>(ErrorHandler)
```

Unresolved references become explicit `ExternalReference` nodes rather than being silently
dropped, so gaps in the scanned scope are visible instead of invisible.

`graph.json` is the pivot of the whole design. `analyze` is the only expensive step;
persisting the graph means `search`, `impact`, `diagrams`, `context` and `report` are fast,
side-effect free, and reproducible. Given the same `graph.json`, they always produce the
same bytes — which is what makes the outputs safe to commit and diff in review.

### BW5 and BW6 in one graph

The two generations have nothing structurally in common — BW5 `.process` files are a
TIBCO-proprietary XML, BW6 `.bwp` files are BPEL 2.0 with TIBCO extensions:

| Concern | BW5 `.process` | BW6 `.bwp` |
|---------|----------------|------------|
| Root | `pd:ProcessDefinition` | `bpws:process` |
| Activity type | `pd:type` (a Java class name) | `bwext:BWActivity/@activityTypeID` (e.g. `bw.jdbc.query`) |
| Entry point | `pd:starter` | `bpws:receive[@createInstance='yes']`, or an HTTP/JMS receive activity |
| Control flow | `pd:transition` | `bpws:link` (with transition conditions) plus `bpws:sequence` order |
| Error handling | error transitions | `bpws:faultHandlers` / `catch` / `catchAll` |

Both are normalised onto the **same node labels, activity categories and relationship
types**, so entry-point detection, complexity, blast radius, search, diagrams and reports
work identically — and a mixed estate mid-migration analyses as one graph. Every
`BWProcess` and `Activity` carries a `bwVersion` property (`BW5` / `BW6`) so you can still
tell them apart, or filter on it.

BW6 activity types resolve by exact `activityTypeID` first, then by plugin family, so an
unrecognised plugin (`bw.kafka.*`, `bw.mongodb.*`, `bw.s3.*`, …) is still categorised as
messaging or database work rather than disappearing into `CUSTOM`.

Not modelled: correlation sets, event handlers and compensation handlers. Activities
nested inside them are still discovered.

---

## Neo4j

Push the export into a **running** database over Bolt:

```bash
pip install "neo4j>=5.0"                       # or: pip install -e ".[neo4j]"
cp .env.example .env                           # then edit .env with your connection

python scripts/push_to_neo4j.py                # load analysis_output/ into neo4j
python scripts/push_to_neo4j.py --dry-run      # show what would be pushed
python scripts/push_to_neo4j.py --wipe --yes   # replace the graph instead of updating it
```

The script reads `neo4j_nodes.csv` and `neo4j_relationships.csv`, creates the constraints and
indexes, then loads both in batched `UNWIND` transactions. It is idempotent — nodes `MERGE` on
`nodeId` and relationships on `(start, end, type)` — so re-running after a fresh `analyze`
updates the graph in place. It finishes by comparing the database counts against the CSVs.
`--via-cypher-shell` replays `neo4j_import.cypher` instead, for hosts without the Python driver.

### Connection settings

`.env.example` is the committed template; copy it to `.env`, which is gitignored so real
credentials never reach the repository. Four keys are read:

| Key | Default | Notes |
|-----|---------|-------|
| `NEO4J_URI` | `bolt://localhost:7687` | `neo4j://` for a cluster, `neo4j+s://` for Aura or TLS |
| `NEO4J_USERNAME` | `neo4j` | |
| `NEO4J_PASSWORD` | — | leave blank in `.env` to be prompted instead of storing it |
| `NEO4J_DATABASE` | `neo4j` | Community edition supports only `neo4j` |

Each value resolves in this order, first hit wins:

```
command-line flag  >  environment variable  >  .env  >  built-in default
```

An exported `NEO4J_PASSWORD` from CI or a secrets manager therefore overrides a developer's
`.env`, not the reverse. The file is looked for in the working directory and then at the
repository root; `--env-file <path>` reads a different one and `--no-env-file` ignores it.
Parsing is dependency-free — no `python-dotenv` — so the script still runs on an air-gapped
agent. It handles `export ` prefixes, `#` comments, and quoted values whose password contains
spaces or a `#`.

For a **stopped** database, `neo4j-admin` bulk import is faster:

```bash
neo4j-admin database import full \
  --nodes=analysis_output/neo4j_nodes.csv \
  --relationships=analysis_output/neo4j_relationships.csv \
  --database=tibco-migration --overwrite-destination
```

…or paste `analysis_output/neo4j_import.cypher` into Neo4j Browser. `analysis_queries.cypher`
holds fifteen verification and analysis queries, each with a stated purpose.

After importing, run the verification queries from `ANALYSIS_QUERIES.md` and confirm the
counts match `context/project-facts.md`. If they differ, the import — not the analysis — is
wrong.

Neo4j is optional. The analyzer answers every built-in question in memory; load the graph
when a team wants to explore interactively or join it to other data.

---

## How semantic search works

Deterministic retrieval, no mandatory model:

- **Corpus** — one document per artefact, mixing structure (names, types, namespaces,
  Spring targets) with behaviour (XPath conditions, SQL, JMS destinations, endpoint URIs,
  log messages). Behaviour is usually what answers a business question. SQL statements,
  the tables they touch, JMS destinations, endpoint URIs and HTTP methods are also promoted
  to node properties, so they are queryable in Neo4j and not only searchable as text.
- **Lexical** — identifier-aware tokenisation (`CreditScoreLookup` → credit, score, lookup),
  BM25 with field boosts and artefact-kind priors, integration-domain synonym expansion.
  Pure standard library: it runs on an air-gapped agent.
- **Vectors (optional)** — `sentence-transformers` locally, or an OpenAI/Azure OpenAI
  embedding endpoint. Unavailable? The engine says so and runs lexical-only.
- **Fusion** — reciprocal rank fusion of both rankings; every hit carries its graph
  neighbourhood, so "where is it" arrives with "and what depends on it".

```bash
pip install -e ".[embeddings]"   # local vectors, offline
export OPENAI_API_KEY=…          # or a hosted provider
tibco-analyze index              # re-index to pick a provider up
```

---

## How blast radius works

A weighted best-first traversal from the changed artefact:

- **Direction** — `upstream` (default) = who depends on this; `downstream` = what this needs;
  `both` = union.
- **Weights** — each relationship type carries a propagation weight (`USES_XSD` 1.0,
  `CALLS` 0.9, `TRANSITIONS_TO` 0.4 …), multiplied by a per-hop decay, so directly coupled
  artefacts outrank distant ones. `BELONGS_TO` is excluded: module membership would drag in
  every sibling and destroy the signal.
- **Output** — impacted artefacts with the path that reached them, the affected *entry
  points* (where a regression becomes externally visible), a risk band, the required test
  scope, and the equivalent Cypher for the same question in Neo4j.

What it cannot see: runtime configuration, deployment descriptors outside the scanned tree,
and data-level coupling between systems. Those limits are stated in the generated reports.

---

## Verifying a run

The analyzer checks its own output. After `analyze`, run the graph gate:

```bash
tibco-analyze -o analysis_output validate --strict     # exit 2 on FAIL or WARN
```

A FAIL means the graph is not trustworthy and no report built on it should ship. Read
`analysis_output/validation_report.md` first. Typical findings and what they mean:

| Finding | Meaning | Action |
|---------|---------|--------|
| `unresolved-references` | A process calls something outside the scanned tree | Widen the export, or accept it as an external boundary |
| `process-has-work` warning | A process with no activities or schemas | Usually a stub or a corrupt export — inspect the file |
| `entry-points-detected` warning | No starters found | The export is probably missing process files, or uses an unmapped starter type |
| `xsd-contains-elements` warning | Schema defines no elements | Often an import-only schema; harmless |

There is no test suite. Verification is this gate plus determinism: two runs over an
unchanged source tree produce the same graph, so diff `graph.json` (or `context/facts.json`)
between runs to see exactly what a source change altered. An unintended change in node or
relationship counts is the signal to look for.

Determinism holds because node ids are assigned in sorted file order, no timestamps are
embedded in the graph itself (only in the metadata block), search ranking is a pure function
of the corpus when embeddings are disabled, and impact traversal is best-first with
deterministic tie-breaking on weight, hops, label and name.

---

## Tuning it to your estate

**Map your activity types.** Every unmapped activity type is categorised `CUSTOM`. Find them:

```bash
python - <<'PY'
import json, collections
g = json.load(open('analysis_output/graph.json'))
raw = collections.Counter(n['properties'].get('rawType','')
                          for n in g['nodes']
                          if n['label']=='Activity'
                          and n['properties'].get('category')=='CUSTOM')
print('\n'.join(f'{c:4}  {t}' for t, c in raw.most_common()))
PY
```

Add each frequent one to `ACTIVITY_SPRING_MAP` in `tools/tibco_analyzer/constants.py` with
its category and Spring Boot equivalent, then re-run `analyze`. This single map drives
categorisation, entry-point detection, the integration surface and the diagrams.

**Turn on vector search if you can.** Lexical search is good on identifiers and literals;
vectors help with paraphrase ("customer onboarding" vs "applicant enrolment"):

```bash
pip install -e ".[embeddings]"    # local, offline, no key
tibco-analyze index
```

**Re-run on every meaningful change.** The analysis is cheap and deterministic. Re-run it
whenever the TIBCO source changes, and diff `context/facts.json` to see exactly what moved.

---

## Wiring the gates into CI

No workflow ships with this repository — the gates are CLI exit codes, so wire them into
whatever CI you already run against your TIBCO source:

- `validate --strict` exits 2 when the graph fails its integrity checks. Run it after
  `analyze` and fail the build on a non-zero exit. Note that `--strict` also fails on
  warnings, and `artifact-coverage` warns whenever under half the supported TIBCO artifacts
  reach the graph. Intentionally unmodelled Java or descriptor files do not trigger it.
- `shared-resource-coverage` is an **error**, not a warning: resource files were discovered
  but none were parsed, which means the integration surface is empty because of a parser
  gap rather than because the estate has no external systems.
- `impact --target <changed artefact> --fail-on CRITICAL` exits 2 when a change has a
  critical blast radius. Run it per changed `.xsd`/`.process` file on pull requests.

Commit `analysis_output/context/` if you want reviewers to see facts change in the diff;
keep the rest generated.

---

## Using it with GitHub Copilot

| Asset | Path | Role |
|-------|------|------|
| Repository instructions | `.github/copilot-instructions.md` | Deterministic-first rules, citation standard, diagram rules, anti-hallucination checklist |
| Agent instructions | `AGENTS.md` | The same contract in short form, for any agent that reads `AGENTS.md` rather than the Copilot files |
| Path-scoped instructions | `.github/instructions/*.instructions.md` | One per estate. Fires when a source artefact is in context — `.process`/`.bwp`/`.xsd` for TIBCO, `f*.sql`/`page_*.sql` for APEX, `.pks`/`.pkb`/`.trg` for Oracle, and `estate_map.json` or `analysis_output_estate/**` for the federation — and routes the question through the analyzer instead of the file |
| Skills | `.github/skills/*/SKILL.md` | Four estate skills (`{tibco,apex,oracle,estate}-analyst`) plus two cross-cutting ones: `analysis-trust` (how to read coverage, provenance and confidence before making a claim) and `migration-planner` (scoping a modernisation from the graph). 19 reference guides in total |
| Prompt files | `.github/prompts/*.prompt.md` | 22 files. Generic: `/graph-analysis`, `/architecture-diagrams`, `/discover-baseline`. Per estate: `/{tibco,apex,oracle,estate}-bootstrap-analysis`, `/{…}-impact-analysis`, `/{…}-neo4j-queries`, `/{tibco,apex,oracle}-security-review`. Specialised: `/tibco-locate-functionality`, `/oracle-data-lineage`, `/estate-data-lineage`, `/estate-cutover-sequence` |
| Chat modes | `.github/chatmodes/*.chatmode.md` | `{tibco,apex,oracle,estate}-analyst`, `{tibco,apex,oracle,estate}-impact`, `{tibco,apex,oracle,estate}-diagrammer` |

A working order for the prompts:

1. `/tibco-bootstrap-analysis` — run the pipeline and summarise what was produced
2. `/graph-analysis`, `/architecture-diagrams`, `/discover-baseline` — complete the three
   step reports by filling their `<!-- LLM: … -->` slots
3. `/tibco-locate-functionality` — answer "where is X implemented?"
4. `/tibco-impact-analysis` — produce a change-impact note for review
5. `/tibco-neo4j-queries` — load the graph into Neo4j and work through the cookbook

Once more than one estate is analysed, the cross-estate prompts follow the same shape:

1. `/estate-bootstrap-analysis` — federate the three graphs and complete the three
   cross-estate reports
2. `/estate-impact-analysis` — the blast radius of one change in every estate at once
3. `/estate-cutover-sequence` — the derived modernisation order, and what must be
   decided before it means anything
4. `/estate-neo4j-queries` — load the federated graph and answer with Cypher

The contract Copilot works under: run the tool, cite the artefact (`file path` + `node id` +
the command that produced the claim), fill only `<!-- LLM: … -->` slots in generated
reports, and never edit a generated table. If a tool result contradicts a prior belief,
the tool wins.

---

## Architecture

Two layers, one boundary:

```
  TIBCO tree        APEX export       Oracle tree      (+ optional
  .process/.bwp     wwv_flow_api      .pks/.pkb/.sql    dictionary
       │                 │                 │             extract)
       ▼                 ▼                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Layer 1 — deterministic (Python, stdlib only)                  │
│                                                                │
│   tibco_analyzer   apex_analyzer   oracle_analyzer             │
│         └────────────────┴────────────────┘                    │
│                   analyzer_core                                │
│         (graph model · ids · SQL+PL/SQL · impact)              │
│                          │                                     │
│                    graph.json ×3                               │
│                          │                                     │
│                          ▼                                     │
│                   estate_analyzer      read-only federation    │
│                          │             (parses no source)      │
│      ┌───────────────────┼───────────────────┐                 │
│      ▼                   ▼                   ▼                 │
│  Neo4j export      search index          diagrams              │
│      └───────────────────┼───────────────────┘                 │
│                          ▼                                     │
│   validation gate ─► context packs + report scaffolds          │
└────────────────────────────────────────────────────────────────┘
                           │  facts only, with coverage attached
                           ▼
┌────────────────────────────────────────────────────────────────┐
│ Layer 2 — GitHub Copilot                                       │
│  instructions · 6 skills · 22 prompts · 12 chatmodes           │
│  interpretation, prioritisation, narrative                     │
└────────────────────────────────────────────────────────────────┘
```

Anything countable, traversable or verifiable belongs to Layer 1. Anything requiring
judgement belongs to Layer 2. A number that appears in a delivered report can always be
traced to a parse; a recommendation can always be traced to a number.

Each analyzer follows the same internal shape, so knowing one is knowing all four. The
TIBCO analyzer, as the worked example:

| Module | Responsibility |
|--------|----------------|
| `constants.py` | TIBCO namespaces, activity→Spring mapping, XSD→Java types, shared-resource map, impact weights, search synonyms |
| `utils.py` | XML parsing helpers, identifier splitting, tier thresholds |
| `model.py` | `GraphNode`, `GraphRel`, `Graph` with adjacency indexes, JSON persistence, reference resolution |
| `parsers/` | One mixin per artefact family plus `crossref.py` for the second, reference-resolving pass |
| `analyzer.py` | Composes the mixins, owns id generation and node/edge creation, orchestrates the run |
| `graph/exporters.py` | Neo4j admin-import CSV pair, runnable Cypher, `analysis_summary.json` |
| `graph/validate.py` | The integrity gate |
| `graph/queries.py` | Cypher cookbook shared by Neo4j users and the skill references |
| `analysis/inventory.py` | Entry points, complexity, dead code, cycles, hotspots, module metrics, integration surface, migration waves |
| `analysis/impact.py` | Weighted blast-radius traversal, risk scoring, test scope, Mermaid rendering |
| `search/` | Corpus construction, BM25, optional embeddings, hybrid fusion, graph-context enrichment |
| `diagrams/` | Mermaid and offline-safe PlantUML generation |
| `report/` | Context packs (`contextpack.py`) and Step report scaffolds (`reports.py`) |
| `cli.py` | Argument parsing, command wiring, exit codes |

---

## Repository layout

> `.github/` is hidden by default in Windows Explorer and macOS Finder. It is visible in
> the GitHub web UI, in the VS Code explorer, and to `git ls-files`; if you are browsing
> an unpacked copy, enable hidden files.

```
README.md                        This document — the only prose documentation
AGENTS.md                        Short agent contract, read by Copilot and other agents
.github/
  copilot-instructions.md        Repo-wide Copilot rules
  instructions/                  Path-scoped rules, one per estate plus the federation
  prompts/                       Task prompt files (TIBCO, APEX, Oracle, cross-estate)
  chatmodes/                     Chat modes (TIBCO, APEX, Oracle, cross-estate)
  skills/tibco-analyst/          TIBCO skill: SKILL.md + seven reference guides
  skills/apex-analyst/           APEX skill: SKILL.md + four reference guides
  skills/oracle-analyst/         Oracle PL/SQL skill: SKILL.md + five reference guides
  skills/estate-analyst/         Cross-estate skill: SKILL.md + three reference guides
  skills/analysis-trust/         Cross-cutting: reading coverage, provenance, confidence
  skills/migration-planner/      Cross-cutting: scoping a modernisation from the graph
                                 — the ONLY editable copies of the skills
tools/analyzer_core/             Dialect-agnostic core, shared by both analyzers
  model.py                       Graph, GraphNode, GraphRel (the deterministic artefact)
  ids.py                         Natural-key node identifiers
  utils.py                       Escaping, hashing, tables, path handling
  cli_base.py                    Logging, graph loading, output helpers
  graph/                         Neo4j exporter, validation engine, cookbook renderer
  analysis/impact.py             Weighted blast-radius engine
  plsql/                         Shared Oracle source analysis used by the APEX and
                                 Oracle analyzers: SQL binder, PL/SQL blocks, DDL
tools/oracle_analyzer/           Oracle PL/SQL analyzer
  analyzer.py                    Orchestrates the Oracle parse
  parsers/                       Source scan, DDL objects, packages and units,
                                 dictionary merge, git history, cross-reference
  analysis/                      Inventory, lineage, metrics, rule catalogue,
                                 business seed (semantics.py), utPLSQL tests
                                 (tests_catalog.py)
  graph/                         Oracle Neo4j schema, Cypher cookbook, validation rules
  diagrams/  report/             Mermaid, reports and context packs
  cli.py                         `oracle-analyze`
tools/apex_analyzer/             Oracle APEX analyzer
  analyzer.py                    Orchestrates the APEX parse
  parsers/                       Export tokenizer, page/region/item/process parsers,
                                 SQL and PL/SQL analysis, name resolution, DDL, git
  analysis/                      Complexity, rule catalogue, inventory, business seed
  graph/                         APEX Neo4j schema, Cypher cookbook, validation rules
  diagrams/  report/             Mermaid/PlantUML, reports and context packs
  extract/                       Read-only SQL kit for the Oracle dictionary extract
  cli.py                         `apex-analyze`
tools/estate_analyzer/           Cross-estate wrapper
  federate.py                    Loads the three graphs, namespaces ids, merges db: nodes
  links.py                       The TIBCO-to-database matcher and the confidence ladder
  analysis/                      Inventory, cross-estate rules, modernisation sequence
  graph/                         Federated Neo4j schema, cookbook, validation rules
  diagrams/  report/             Mermaid, context packs and report scaffolds
  cli.py                         `estate-analyze`
tools/tibco_analyzer/
  analyzer.py                    Orchestrates the parse
  parsers/                       .process, .xsd/.aeschema, .wsdl, shared resources,
                                 .substvar, XSLT, cross-reference resolution
  graph/                         Neo4j exporters, validation gate, Cypher cookbook
  analysis/                      Inventory, complexity, dead code, cycles, impact engine
  search/                        Corpus, BM25, optional embeddings, hybrid engine
  diagrams/                      Mermaid and offline-safe PlantUML generators
  report/                        Context packs and Step 00/01/02 report scaffolds
  cli.py                         Command line interface
tests/
  fixtures/apex/                 A small APEX export + schema DDL with seeded defects
  fixtures/oracle/               A small Oracle estate: packages with spec and body, an
                                 overload, dynamic SQL, an unresolvable call, a
                                 user-defined type, and a utPLSQL suite
  fixtures/tibco/                One BW5 and one BW6 module, since the two generations
                                 share almost no file conventions
  fixtures/estate/               The cross-estate fixture: a mapped BW6 module, an
                                 unmapped BW5 one, a near-miss table name, a runtime-SQL
                                 activity, the estate map and the expected join
  test_apex_analyzer.py          End-to-end APEX tests (determinism, rules, export)
  test_oracle_analyzer.py        End-to-end Oracle tests (overloads, lineage, coverage)
  test_tibco_analyzer.py         End-to-end TIBCO tests, both generations
  test_sql_binder.py             The SQL/PL-SQL binder corpus — the quality net
  test_estate_analyzer.py        The three fixtures federated: the join, its confidence
                                 ladder, its coverage gates and its blind spots
scripts/
  push_to_neo4j.py               Loads the neo4j_* export into a running Neo4j over Bolt
.env.example                     Template for Neo4j connection settings (copy to .env)
```

The skills live only in `.github/skills/`. There is no generated bundle and nothing to
keep synchronised — edit them in place. Two reference files are generated rather than
written: each `cypher-cookbook.md` is rendered from that analyzer's `graph/queries.py`,
and carries the command to regenerate it in a comment at the top.

---

## Extending it

- **New activity type** — add one entry to `ACTIVITY_SPRING_MAP` in `constants.py`; the
  category, Spring target, diagrams and reports follow automatically.
- **New artefact type** — add a parser mixin in `parsers/`, register it in
  `analyzer.py::analyze`, and add validation expectations in `graph/validate.py`.
- **New analysis question** — add a function in `analysis/inventory.py` and a query in
  `graph/queries.py` so the local engine and Neo4j stay in step.
- **New report section** — add it to `report/reports.py`; use a `<!-- LLM: … -->` marker for
  anything the model should write.

After any change, re-run the pipeline against a real TIBCO tree and confirm
`validate --strict` still passes — see [Verifying a run](#verifying-a-run).

## Licence

MIT. The analyzer contains no TIBCO or third-party proprietary code.
