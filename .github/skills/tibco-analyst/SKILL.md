---
name: tibco-analyst
description: Analyse a legacy TIBCO BusinessWorks estate with this repository's deterministic analyzer before a Spring Boot migration — use when asked to analyse a TIBCO project, read TIBCO BusinessWorks or BW artefacts (.process, .bwp, .xsd, .wsdl, .substvar, shared resources), build or query a Neo4j knowledge graph of TIBCO, produce TIBCO architecture diagrams, find where a piece of business functionality is implemented in TIBCO, work out the blast radius or impact of changing a TIBCO artefact, or assess TIBCO to Spring Boot migration scope, complexity, sequencing and risk.
---

# TIBCO BusinessWorks analysis

## What this skill is for

This repository ships a two-layer solution:

| Layer | What it does | Who owns it |
|-------|--------------|-------------|
| 1 — deterministic | `tools/tibco_analyzer` parses the TIBCO source tree into a knowledge graph (`graph.json`), Neo4j exports, context packs, diagrams and report scaffolds | The Python CLI |
| 2 — narrative | Explains, prioritises and writes up those facts | You |

Use the skill when the question is about an existing TIBCO BusinessWorks estate:
inventory, architecture, coupling, complexity, dead code, data contracts,
migration sequencing, or the consequence of changing something.

Do not use it for writing new TIBCO code, for runtime/production troubleshooting,
or for questions about a Spring Boot codebase that has already been migrated.

## The rule that is not negotiable

**Deterministic first. The analyzer produces facts; you produce meaning.**

1. If `analysis_output/graph.json` does not exist, you have no facts. Run `analyze`
   before answering anything, or say plainly that the analysis has not been run.
2. Never state a count, a component, a dependency, an endpoint or a risk that you
   cannot point at in analyzer output.
3. If the analyzer did not find something, the correct answer is "not present in
   the scanned tree" — never a plausible guess about what a TIBCO project usually
   contains.
4. Raw XML is a last resort, used only to quote a specific line after the graph has
   told you which file to open. It is never the basis of a count.

## Invocation

From the repository root:

```bash
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output <subcommand>
```

If the package is installed (`pip install -e .`), the equivalent is:

```bash
tibco-analyze -o analysis_output <subcommand>
```

`-o/--output` defaults to `analysis_output`. Every subcommand except `analyze`
reads `<output>/graph.json`, so the expensive parse happens once.

Exit codes: `0` success, `1` usage or runtime error, `2` gate failure
(`validate` FAIL, `validate --strict` on WARN, or `impact --fail-on` reached).

## Standard workflow

Run in this order. Each step consumes the previous step's output.

| # | Command | Produces | Why it matters |
|---|---------|----------|----------------|
| 1 | `analyze --source <tibco_root>` | `graph.json`, `neo4j_nodes.csv`, `neo4j_relationships.csv`, `neo4j_import.cypher`, `analysis_summary.json`, `analysis_queries.cypher`, `ANALYSIS_QUERIES.md` | The single source of truth |
| 2 | `validate [--strict]` | `validation_report.md` / `.json` | Gate: a FAIL means nothing downstream is trustworthy |
| 3 | `index [--no-embeddings] [--provider ...]` | `search_index/` | Enables `search`; BM25 works offline, vectors are optional |
| 4 | `context` | `context/*.md`, `context/processes/<Name>.md`, `facts.json`, `MANIFEST.md` | The packs you read instead of raw XML |
| 5 | `diagrams [--format mermaid\|plantuml\|both]` | `generated_diagrams/**` | Architecture views, every element graph-derived |
| 6 | `report` | `reports/Step00…`, `Step01…`, `Step02…`, `inventory.json` | Scaffolds with `<!-- LLM: ... -->` slots for you |

`all --source <tibco_root>` runs analyze → validate → index → diagrams → context →
report in one pass and returns the validation exit code. Use it for a first run;
use the individual commands when re-running one stage after a source change.

Two further commands exist: `search` (Playbook B), `impact` (Playbook C) and
`queries` (rewrites the Cypher cookbook without re-parsing).

---

## Playbook A — full project assessment

**Question shape:** "Analyse this TIBCO project", "how big is the migration",
"what should we migrate first", "give me the baseline for a Spring Boot move".

### Commands

```bash
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output all --source <tibco_root>
```

If `all` is not appropriate (for example the index already exists and embeddings
are expensive), run steps 1–6 individually.

### How to read the output

Read in this order and stop when you have what the question needs:

1. `analysis_output/validation_report.md` — status first. PASS, WARN or FAIL.
2. `analysis_output/context/project-facts.md` — totals, node/relationship counts,
   artefact families, modules, tier mix. Every number you quote about size comes
   from here.
3. `analysis_output/context/entry-points.md` — the externally reachable surface and
   its Spring Boot target. This is the migration's contract boundary.
4. `analysis_output/context/complexity.md` — ranking, change hotspots,
   error-handling gaps, circular dependencies.
5. `analysis_output/context/data-contracts.md` — schemas, namespaces, consumers,
   WSDL operations. These are the parity-test acceptance criteria.
6. `analysis_output/context/integration-surface.md` — outbound integrations, shared
   resources, global variables (the future `application.yml`).
7. `analysis_output/context/dead-code.md` — artefacts nothing references.
8. `analysis_output/context/migration-sequence.md` — dependency-ordered waves.
9. `analysis_output/context/processes/<Name>.md` — open one per process you intend
   to describe. Do not describe a process without opening its pack.

### How to write it up

Fill the `<!-- LLM: ... -->` slots in `analysis_output/reports/`. Do not restructure
the reports and do not touch the generated tables. See
`references/report-templates.md` for the section-by-section quality bar.

A good assessment answers, in this order: how large, what is externally exposed,
where the complexity concentrates, what is most reused (highest blast radius),
what is dead, what blocks incremental migration (cycles), and what the first wave is.
Every one of those is a number the analyzer already computed.

### Failure modes

| Symptom | Meaning | Action |
|---------|---------|--------|
| `Graph not found at .../graph.json` | `analyze` has not run for this output dir | Run step 1; check `--output` matches |
| Validation `FAIL` | Referential integrity, duplicate ids, or missing required edges (`BELONGS_TO`, `EXECUTES`, `CONTAINS`) | Stop. Report the failing rules verbatim. Do not build a report on a failed graph |
| Validation `WARN` | Orphans, unresolved references, XSDs with no elements, no entry points detected | Continue, but carry the warning into the report's limitations and risk sections |
| 0 BWProcess nodes | Wrong `--source`, or a BW6/CE tree whose `.bwp` files were not parsed | Re-check the root; state what was and was not found rather than inferring |
| `unresolved-references` warning | Processes call artefacts outside the scanned tree, materialised as `ExternalReference` nodes | Name them as scope gaps; do not assume what they do |

---

## Playbook B — locate functionality (semantic search)

**Question shape:** "Where is credit scoring implemented?", "which process writes to
the customer queue?", "where is the validation for X?".

### Commands

```bash
# once, after analyze
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output index --no-embeddings

PYTHONPATH=tools python -m tibco_analyzer -o analysis_output \
  search "where is credit scoring calculated" --top 10
```

Useful flags: `--label BWProcess` (repeatable), `--module CreditApp.module`
(repeatable), `--top N`, `--json`, `--save <path>`.

### How to read the output

Each hit carries its graph neighbourhood, which is what makes it actionable:

- **File / Node** — the citation you must quote (`bwp_0004`, path relative to root).
- **Why** — the generated snippet: entry type, activity count, tier.
- **Matched terms** — the query tokens that actually hit. If these are only generic
  words, the hit is weak.
- **Entry point / Uses schemas / Calls / Used by / Spring targets** — the context you
  need to answer the follow-up question before it is asked.

Rank order comes from BM25 with label priors fused with optional vectors, so a
process outranks a single element for the same evidence. Treat ranking as a
shortlist, not a verdict.

### How to write it up

Name the artefact, its file, its node id, and the evidence that it is the right
one (matched terms plus graph context). Then confirm by opening
`context/processes/<Name>.md` and describing the actual activity sequence. Close
with the consequence: who calls it, what it uses, and — if the user is changing it
— run Playbook C.

### Failure modes

| Symptom | Meaning | Action |
|---------|---------|--------|
| `Search index not found` | `index` has not run | Run `index`; add `--no-embeddings` if offline |
| `candidates: 0` / no matches | Vocabulary gap, not absence | Retry with domain terms actually used in the estate (activity names, queue names, table names), or drop to a single distinctive noun. Then say plainly that no artefact matched |
| Only `Element` / `ComplexType` hits | The concept exists as data, not behaviour | Report it as a data concept and search for its consuming process via the schema's consumers in `data-contracts.md` |
| Matched terms are all synonyms | Query expansion, not a direct hit | Lower confidence; verify against the process pack before asserting |
| Mode is `lexical` when vectors were expected | No embedding provider available | State the mode. `--provider sentence-transformers` or an API key plus re-`index` is the fix; lexical results remain valid |

Do not paper over a weak result. "No artefact in the scanned tree matches X" is a
finding; an invented match is a defect.

---

## Playbook C — blast radius / impact of change

**Question shape:** "What breaks if we change CreditResponse.xsd?", "what is the
impact of retiring this sub-process?", "which services depend on this global
variable?".

### Commands

```bash
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output \
  impact --target "XSD:CreditResponse" --depth 4 --direction upstream

# CI gate, with saved artefacts
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output \
  impact --target "BWProcess:ScoreCalculationProcess" \
  --direction upstream --fail-on HIGH --save analysis_output/impact/score-calc
```

Targets accept a node id (`xsd_0002`), an exact name, `Label:Name`, or a file path.
`--save <stem>` writes `.md`, `.json` and `.mmd`. Other flags: `--depth N`,
`--direction upstream|downstream|both`, `--include-rel`, `--exclude-rel`,
`--all-matches`, `--label`, `--json`.

Default direction is `upstream` — who depends on the target. That is the blast
radius. `downstream` answers "what must be in scope to migrate this".

### How to read the output

- **Risk band** (LOW/MEDIUM/HIGH/CRITICAL) and score — comparative, not absolute.
  Compare targets against each other; never present the score as a calibrated metric.
- **Affected entry points** — the externally visible regressions. This is the most
  important table: if it is empty, the change is internal.
- **Impacted artefacts** — sorted by coupling weight, with hop count and the
  relationship path. Hop 1 with weight 0.75 is direct coupling; a 4-hop 0.04 tail is
  noise you should not lead with.
- **Required test scope** — the contract, regression, marshalling and service tests
  that must run.
- **Equivalent Cypher** — hand this to anyone who has loaded the graph into Neo4j.

`BELONGS_TO` edges are never traversed, so module membership does not drag the
whole module into the result.

### How to write it up

Lead with the entry points affected and the risk band, then the direct (hop 1–2)
dependants, then the test scope. State the parameters used (target, depth,
direction) because the result is only meaningful with them. Finish with the limits
in `references/impact-analysis.md` — the analysis sees the scanned tree only.

### Failure modes

| Symptom | Meaning | Action |
|---------|---------|--------|
| `no artefact matches '<ref>'` (exit 1) | Wrong name or the artefact is not in the graph | Run `search "<ref>"` first, then use the node id from the hit |
| `Ambiguous target '<ref>' — N matches` (exit 1) | The reference matches several labels/nodes | Re-run with `--label`, the exact node id, or `--all-matches` if the union really is the question. Never pick one silently |
| `Impacted artefacts: 0` | Nothing depends on it at this depth | Report it as genuinely isolated, and check whether it appears in `dead-code.md` |
| Huge result at depth 6+ | Transitive noise | Reduce depth to 3–4, or use `--include-rel USES_XSD --include-rel IMPORTS_SCHEMA` for a contract-only view |
| Exit code 2 | `--fail-on` threshold reached | That is the gate working; report the band, do not re-run with a weaker threshold to make it pass |

---

## Playbook D — architecture diagrams

**Question shape:** "Draw the architecture", "show the process flow", "what does
the integration surface look like?".

### Commands

```bash
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output diagrams --format both
```

Output lands under `analysis_output/generated_diagrams/`:

| Path | View |
|------|------|
| `mermaid/architecture-flows/system-context.mmd` | Consumers → entry points → external systems |
| `mermaid/component-diagrams/module-containers.mmd` | One box per module, with cross-module call counts |
| `mermaid/component-diagrams/components.mmd` | Processes, their schemas and resources |
| `mermaid/architecture-flows/process-dependencies.mmd` | Process-to-process call hierarchy |
| `mermaid/architecture-flows/process-<name>.mmd` | Activity flow for one process (top 12 by complexity) |
| `mermaid/architecture-flows/integration-surface.mmd` | Shared resources and external systems |
| `mermaid/data-flow-diagrams/schema-usage-map.mmd` | Which process uses which schema |
| `mermaid/er-diagrams/canonical-data-model.mmd` | ER view from XSD complex types |
| `plantuml/c4-models/{context,container,component}.puml` | C4-style views, offline-safe syntax |
| `plantuml/deployment-diagrams/topology.puml` | Runtime and external system topology |
| `plantuml/sequence-diagrams/sequence-<name>.puml` | Runtime sequence for one process (top 8) |

### How to read and present them

Pick the smallest diagram that answers the question — a process flow beats a
whole-estate component map for "how does this flow work". Quote the file path so the
reader can regenerate it. Mermaid renders in GitHub and VS Code; PlantUML renders
with a local server (`plantuml -tsvg <file>.puml`).

Before presenting a hand-written supplementary diagram, verify every box and arrow
against the graph. `references/diagram-standards.md` sets out the forbidden PlantUML
directives, the naming conventions and the verification checklist.

### Failure modes

| Symptom | Meaning | Action |
|---------|---------|--------|
| `No inter-process calls detected` | Real finding: the estate is flat, or calls are unresolved | Cross-check `CALLS_EXTERNAL` and `ExternalReference` nodes before calling it flat |
| `No shared resources detected` | No `.sharedhttp`/`.sharedjdbc`/… files parsed | State it; do not draw an assumed database |
| Diagram too dense to read | Views cap at 40–60 nodes and are still large | Narrow to a module or a single process view rather than editing the generated file |
| A component you expected is missing | It is not in the graph | Do not add it. Report the gap, with the `ExternalReference` or dead-code evidence if there is any |

---

## Evidence and citation standard

Every factual claim carries three things:

1. **File path** — repository-relative, e.g.
   `CreditApp.module/Processes/MainCreditProcess.process`.
2. **Node id** — e.g. `bwp_0002`, `xsd_0002`. Ids are stable for a given parse and
   are how a reader verifies you in Neo4j.
3. **The command that produced it** — e.g.
   `impact --target "XSD:CreditResponse" --depth 4 --direction upstream`.

Worked example of the expected density:

> `MainCreditProcess` (`bwp_0002`,
> `CreditApp.module/Processes/MainCreditProcess.process`) is an `HTTP_RECEIVER`
> entry point with 10 activities and complexity 24.0 (High tier), per
> `context/entry-points.md` and `context/complexity.md`. Changing
> `CreditResponse` (`xsd_0002`) reaches it at hop 1 with weight 0.75 —
> `impact --target "XSD:CreditResponse" --depth 4 --direction upstream`, risk band
> MEDIUM, three entry points affected.

Numbers without a source are the single most common defect in this domain. If a
figure is not in analyzer output, do not produce it.

## Never do this

- **Never estimate a count.** Not processes, activities, schemas, endpoints, lines
  or effort-days. Counts come from `project-facts.md` / `facts.json` or they do not
  appear.
- **Never describe a process you have not opened a context pack for.** Naming a
  process in a table is fine; describing its behaviour without
  `context/processes/<Name>.md` is not.
- **Never draw a component that is not in the graph.** No assumed load balancer,
  cache, gateway or database. If a mock or placeholder is unavoidable in a
  supplementary diagram, label it explicitly as such.
- **Never edit generated tables in the reports.** Fill only `<!-- LLM: ... -->`
  slots. If a table is wrong, the parser or the source is wrong — fix that and
  re-run `report`.
- **Never use remote PlantUML includes** (`!include https://...`, C4-PlantUML macros)
  or `!theme`. Diagrams must render on an offline server.
- **Never present the impact risk score as an absolute measure.** It is comparative.
- **Never silently resolve an ambiguous impact target.** Report the candidates.
- **Never claim a capability the CLI does not have.** There is no code generation, no
  runtime tracing, no test execution and no automatic Spring Boot scaffolding here.

## Reference files

Read the one that matches the task; do not inline them all.

| File | Read it when you need |
|------|----------------------|
| `references/graph-model.md` | Node labels, relationship semantics, key properties, Spring Boot targets, the canonical per-process subgraph, how `ExternalReference` marks unresolved references |
| `references/cypher-cookbook.md` | Loading the graph into Neo4j and the verification / analysis queries, each with its purpose and expected result shape |
| `references/semantic-search.md` | How the index ranks, how to phrase queries for a TIBCO estate, filters, and a worked business-question example |
| `references/impact-analysis.md` | How blast radius is computed, choosing depth and direction, reading test scope, worked schema / sub-process / global-variable examples, and the limits |
| `references/diagram-standards.md` | Which diagram answers which question, Mermaid vs PlantUML, forbidden directives, naming conventions, verification checklist |
| `references/report-templates.md` | Step00/01/02 structure, generated vs LLM sections, the `<!-- LLM: ... -->` convention, quality bar and final review checklist |
