# Oracle APEX analysis

Deterministic analysis of an Oracle APEX application: a knowledge graph of pages,
regions, items, processes, the SQL and PL/SQL they run, and the database objects that
SQL touches — plus blast radius, rule findings, diagrams, Neo4j export and LLM
context packs.

Same contract as the TIBCO side of this repository: **the analyzer produces facts,
the agent produces meaning.** No count, dependency or risk in any output comes from a
language model.

The graph vocabulary is defined in code, not in a document:
[`tools/apex_analyzer/constants.py`](../tools/apex_analyzer/constants.py) holds every label,
relationship type, impact weight and typed property, and
[`graph/validate_rules.py`](../tools/apex_analyzer/graph/validate_rules.py) fails the build on
anything outside it. For the model explained rather than enumerated, read
[`.github/skills/apex-analyst/references/`](../.github/skills/apex-analyst/references/) —
`graph-model.md`, `sql-binding.md`, `rule-catalogue.md` and `cypher-cookbook.md`.

---

## Quick start

```bash
# 1. Export the application (SQLcl), or point at an export already in the repo
sql> apex export -applicationid 100 -split

# 2. Optional but strongly recommended: the database dictionary extract
sql> @tools/apex_analyzer/extract/run_all.sql 100 ORDER_APP
python tools/apex_analyzer/extract/merge_parts.py db_meta_parts.json db_meta.json

# 3. Analyse
PYTHONPATH=tools python -m apex_analyzer -o analysis_output_apex all \
  --source ./f100 --db-meta db_meta.json

# 4. Load into Neo4j
python scripts/push_to_neo4j.py -o analysis_output_apex --dataset app100@<hash>
```

Installed instead of `PYTHONPATH`:

```bash
pip install -e .
apex-analyze -o analysis_output_apex all --source ./f100 --db-meta db_meta.json
```

Python 3.9+, standard library only. `neo4j>=5.0` is needed only for the push script.

---

## What it reads

| Mode | Input | Status |
|---|---|---|
| Split export | `f100/application/**/*.sql` (`apex export -split`) | **supported** — preferred, because the Git layer works file by file |
| Single-file export | `f100.sql` | **supported** — parsed identically; the Git layer degrades to file level |
| Schema DDL | `create table` / `package body` scripts committed alongside | **supported** — this is how the database layer is built with no dictionary access |
| Dictionary extract | `db_meta.json` from `tools/apex_analyzer/extract` | **supported** — adds row counts, synonyms, `ALL_DEPENDENCIES`, real program units |
| Readable YAML export | `f100/readable/**` (`-expType READABLE_YAML`) | **not implemented** — the analyzer detects it and tells you to use the SQL export |

Both `wwv_flow_api.*` (APEX ≤ 21.1) and `wwv_flow_imp*.*` (21.2+) export APIs are
handled: procedures are matched by name, and the package prefix is recorded but not
depended on.

---

## Commands

```
apex-analyze analyze   --source <export_root> [--app-id 100] [--schema ORDER_APP]
                       [--db-meta db_meta.json] [--apex-meta apex_meta.json]
                       [--git] [--git-range v1.2..HEAD]
apex-analyze validate  [--strict]                     # CI gate, exit 2 on failure
apex-analyze rules     [--category SECURITY] [--min-severity HIGH] [--fail-on CRITICAL]
apex-analyze impact    --target "DbTable:ORDERS" [--direction upstream|downstream|both]
                       [--depth 8] [--fail-on HIGH] [--save <path stem>]
apex-analyze diagrams  [--format mermaid|plantuml|both]
apex-analyze context                                  # LLM grounding packs
apex-analyze report                                   # Step00/01/02 scaffolds
apex-analyze queries   [--print-queries]              # Cypher cookbook
apex-analyze diff      --baseline <older graph.json>  # release comparison
apex-analyze all       --source <export_root>         # everything, in order
```

Exit codes: `0` ok, `1` usage or runtime error, `2` gate failure.

---

## What it produces

```
analysis_output_apex/
  graph.json                  The deterministic artefact every other command reads
  neo4j_nodes.csv             Typed node table (nodeId:ID, label:LABEL, …)
  neo4j_relationships.csv     Edge table (:START_ID, :END_ID, :TYPE, …)
  neo4j_import.cypher         Standalone script for cypher-shell
  neo4j_indexes.json          Constraints, indexes and full-text indexes to create
  analysis_queries.cypher     The query cookbook, runnable
  ANALYSIS_QUERIES.md         The same, with explanations
  analysis_summary.json       Counts, tiers, findings, coverage
  validation_report.md/.json  The gate's verdict
  context/                    Grounding packs an agent reads instead of the export
  reports/                    Step00/01/02 scaffolds with <!-- LLM: … --> sections
  generated_diagrams/         Mermaid and PlantUML sources
```

---

## Reading the coverage figure

Every run reports how much of the SQL resolved to real database objects:

```
  COVERAGE:
   ingestion mode           : split
   dictionary available     : True
   resolution coverage      : 97% (33/34)
   unresolved objects       : ORDER_APP.ORDERS_ARCHIVE
```

Below 80 % the validator raises `AX-COVERAGE` and the graph is provisional. Quote the
figure before making any claim about completeness. An unresolved reference is kept in
the graph as a `:DbObject:Unresolved` node and raised as `CORR-001`, so "the analyzer
does not know" is always visible rather than silently absent.

---

## What is implemented, and what is not

| Area | State |
|---|---|
| Export parsing | Application, pages, regions, items, buttons, processes, validations, branches, computations, dynamic actions, report/IR/IG columns, and the shared components. Export procedures no parser handles are **counted and reported** in `graph.meta.unhandledProcedures`, never silently dropped. |
| Database layer | Built from a dictionary extract (`--db-meta`) and/or DDL committed in the repository — tables, columns, constraints, views, packages, program units, triggers, sequences, synonyms. |
| The binder | SQL and PL/SQL analysis, the six-step resolution ladder with a confidence on every inferred edge, CTE suppression, bind variables, declarative `SOURCED_FROM`, column-level lineage, and a cross-check against `ALL_DEPENDENCIES`. |
| Analysis | Page and application complexity, fan-in/fan-out, 24 graph rules plus 3 raised during parsing, the validation gate, a derived business-function seed, and release comparison by natural key. |
| Delivery | `graph.json`, Neo4j CSV/Cypher/index sidecar, Cypher cookbook, context packs, Step00/01/02 reports, Mermaid and PlantUML. |
| Change layer | `--git` / `--git-range` records repository, branch, commit and `CHANGED` edges. |

Deliberately absent:

| Gap | Why | What happens instead |
|---|---|---|
| Readable YAML export (`-expType READABLE_YAML`) | The SQL export carries the same facts | The analyzer detects a readable-only export and asks for the SQL export |
| `search` / `index` for APEX | The search stack still lives in `tools/tibco_analyzer` and is coupled to its corpus vocabulary | The context packs, `rules`, `impact`, and the Neo4j full-text indexes the exporter declares |
| `--apex-meta` count cross-check | The extract kit emits the file and the flag is accepted, but the comparison against the export parse is not wired | `AX-CROSSCHECK` reports unhandled export procedures only |
| Live Oracle connection | Would break the zero-dependency, offline property | The read-only SQL kit in [`tools/apex_analyzer/extract`](../tools/apex_analyzer/extract/) |

The analyzers share [`tools/analyzer_core/`](../tools/analyzer_core/) — the graph model, node
ids, the Neo4j exporter, the validation engine and the blast-radius engine. `tibco_analyzer`
still carries its own exporter, validator and impact copies; deduplicating those is the one
piece of the shared-core move left to do, and it is why `tibco_analyzer/model.py` is a
re-export shim.

---

## The validation gate

`apex-analyze validate --strict` exits 2 on failure and is the CI gate. Its rules:

| Rule | Severity | Check |
|---|---|---|
| `AX-IDS` | ERROR | node ids unique and matching the id grammar |
| `AX-REFS` | ERROR | every relationship endpoint exists |
| `AX-VOCAB` | ERROR | no label or relationship type outside `constants.py` |
| `AX-CONTAIN` | ERROR | every page has an application, every region a page, every column a table |
| `AX-TYPES` | ERROR | typed properties parse as their declared type |
| `AX-PROV` | ERROR | an agent-authored node with no evidence, or an inferred edge with no confidence |
| `AX-COVERAGE` | WARNING | resolution coverage below 80 %, or more than 5 % of code nodes failed to parse |
| `AX-CROSSCHECK` | WARNING | export calls no parser handled |
| `AX-DEPMISMATCH` | WARNING | inferred `CALLS` edges not confirmed by `ALL_DEPENDENCIES` |
| `AX-ORPHAN` | WARNING | nodes with no edges, excluding tolerated labels |

A FAIL means the graph is not trustworthy and nothing should be built on it.

---

## Neo4j

```bash
python scripts/push_to_neo4j.py -o analysis_output_apex --dataset app100@a1b2c3d4e5f6
```

- `--dataset` deletes only that application's nodes before loading, leaving other
  applications and the shared database layer intact. Use it on any shared instance;
  `--wipe` clears everything.
- Constraints, indexes and full-text indexes come from `neo4j_indexes.json`, so the
  same script serves both analyzers.
- Loading is idempotent: nodes `MERGE` on `nodeId`, so a re-run updates in place.
- For a first bulk load of a very large estate, `neo4j-admin database import full`
  consumes the same CSVs — pass `--multiline-fields=true`, because SQL text legally
  contains newlines.

Because node ids are natural keys (`app100:p10:r1001`, `db:ORDER_APP.ORDERS`), two
releases can be compared by set arithmetic — that is what `apex-analyze diff` does
locally, and what makes an incremental re-load safe.

---

## Verifying a change

```bash
python tests/test_apex_analyzer.py      # end to end, on the committed fixture
python tests/test_sql_binder.py         # the SQL/PL-SQL corpus
pytest tests                            # both, if pytest is installed
```

The parse is deterministic, so after any parser change, re-analyse a real export and
diff `graph.json` — an unintended change in node or relationship counts is the signal
to look for. When the binder gets a statement wrong, add the snippet to
`tests/test_sql_binder.py` with what it should extract; that file is the measure of
the analyzer's quality.

---

## Working with an agent

The skill is at `.github/skills/apex-analyst/`, with three chat modes and four prompts:

| Asset | Use it for |
|---|---|
| `apex-analyst` chat mode | general analysis: inventory, dependencies, lineage, scoping |
| `apex-impact` chat mode | change review: what breaks if this table, package or page changes |
| `apex-diagrammer` chat mode | producing and validating diagrams in which every element traces to a node |
| `/apex-bootstrap-analysis` | run the pipeline and write the narrative sections of the reports |
| `/apex-impact-analysis` | one blast-radius assessment, end to end |
| `/apex-security-review` | the security findings, ranked, with what rules cannot cover |
| `/apex-neo4j-queries` | load the graph and answer a question in Cypher |

Each chat mode carries its own refusal conditions — the diagrammer will not draw a
component that is not in the graph, and the impact mode will not claim completeness when
resolution coverage is below 80 %.

The rule an agent must not break: if a fact is in `analysis_output_apex/context/`,
cite it from there; if it is not, run the command that produces it. Reading
`f100.sql` to count anything is a defect.
