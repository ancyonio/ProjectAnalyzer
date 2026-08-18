---
name: apex-analyst
description: Analyse an Oracle APEX application with this repository's deterministic analyzer — use when asked to analyse an APEX application or export, read APEX artefacts (f100.sql, split exports, wwv_flow_imp calls, pages, regions, items, processes, dynamic actions, LOVs), build or query a Neo4j knowledge graph of APEX, work out the blast radius of changing a table, view, package or procedure, trace which pages use a column, find dead pages or unused shared components, review APEX security posture and SQL performance, or scope an APEX modernisation.
---

# Oracle APEX analysis

## What this skill is for

The repository ships a two-layer solution:

| Layer | What it does | Who owns it |
|---|---|---|
| 1 — deterministic | `tools/apex_analyzer` parses the APEX export and the schema into a knowledge graph (`graph.json`), Neo4j exports, context packs, diagrams, rule findings and report scaffolds | The Python CLI |
| 2 — narrative | Explains, prioritises and writes up those facts | You |

Use it when the question is about an existing APEX application: inventory,
dependencies, data lineage, security posture, SQL performance, dead code, change
impact or modernisation scope.

Do not use it to write new APEX code, to troubleshoot a running instance, or to
answer questions about a schema with no APEX application in front of it.

## The rule that is not negotiable

**Deterministic first. The analyzer produces facts; you produce meaning.**

1. If `analysis_output_apex/graph.json` does not exist, you have no facts. Run
   `analyze`, or say plainly that the analysis has not been run.
2. Never state a count, a page, a dependency, a table or a risk you cannot point at
   in analyzer output.
3. Reading `f100.sql` or a `page_000NN.sql` to count regions, guess a caller or infer
   a dependency is a defect, not diligence. Open an export file only to *confirm*
   something a command already surfaced, or to quote a line the graph does not model.
4. Always state coverage before making a claim about completeness. `coverage` in
   `graph.meta` reports how much of the SQL resolved to real database objects; below
   80 % the graph is provisional and you must say so.

## Invocation

From the repository root (Python 3.9+, no third-party packages needed):

```bash
# no install
PYTHONPATH=tools python -m apex_analyzer -o analysis_output_apex <subcommand>

# installed
pip install -e . && apex-analyze -o analysis_output_apex <subcommand>
```

Before answering any analysis question:

```bash
PYTHONPATH=tools python -m apex_analyzer -o analysis_output_apex analyze \
  --source <export_root> [--db-meta db_meta.json]
PYTHONPATH=tools python -m apex_analyzer -o analysis_output_apex validate
```

`analyze` is the only command that reads the export; everything else reads
`analysis_output_apex/graph.json`. If validation reports FAIL, stop — say the graph
is not trustworthy and quote the failing rules.

## Where the answers already are

| Question | Route |
|---|---|
| Size, coverage, tiers | `analysis_output_apex/context/application-facts.md` |
| Every page and its metrics | `context/pages.md` |
| Which page touches which table | `context/data-access.md` |
| Authorization coverage, public surface | `context/security.md` |
| Rule findings with evidence | `context/findings.md` — or `apex-analyze rules` |
| Unreachable pages, unused components | `context/dead-code.md` |
| One page in full, including its code | `context/pages/page_<id>.md` |
| "What breaks if I change X?" | `apex-analyze impact --target "DbProgramUnit:CREATE_ORDER"` |
| Release comparison | `apex-analyze diff --baseline <old graph.json>` |

## Task playbooks

### Understand an application
1. `analyze`, `validate`, `report`, `context`.
2. Read `context/application-facts.md` and `reports/Step00_APEX_GRAPH_REPORT.md`.
3. Answer from the tables. Quote page ids and node ids.

### Impact of a database change
1. `apex-analyze impact --target "DbTable:ORDERS" --direction upstream`.
2. Report the affected pages first (they are what users see), then the components.
3. Every claim carries its hop count from the report — do not round it into prose
   like "widely used".

### Security review
1. `apex-analyze rules --category SECURITY`.
2. Cross-read `context/security.md` for pages with no authorization scheme.
3. Rank by severity, then by whether the page writes to the database.
4. Never soften a CRITICAL finding; SEC-001 is an injection path, not a style issue.

### SQL performance review
1. `apex-analyze rules --category PERFORMANCE`.
2. Read the offending `:SqlStatement` node's properties (join count, select star,
   hints, bind count) from the page pack.
3. Recommend against the specific statement hash, not "the report".

### Modernisation scoping
1. Use `complexityScore`, `tier` and `fanOut` from `context/pages.md`.
2. Sequence by tier and by shared dependency (a page reaching a high-`fanIn` table
   cannot move alone).

## Sibling chat modes

Two of the playbooks above have a dedicated chat mode with stricter refusal conditions;
switch to it rather than working freehand:

| Chat mode | Use it when |
|---|---|
| `apex-impact` | the question is "what breaks if this changes" — it enforces resolving the target to a node, running `impact`, and stating the confidence of every path |
| `apex-diagrammer` | the answer is a diagram — it enforces that every box and arrow traces to a node and an edge, and refuses invented infrastructure |

## Reference guides

- [graph-model.md](references/graph-model.md) — labels, relationships, ids, provenance
- [cypher-cookbook.md](references/cypher-cookbook.md) — the queries and when to use them
- [rule-catalogue.md](references/rule-catalogue.md) — every rule, what triggers it
- [sql-binding.md](references/sql-binding.md) — how SQL becomes edges, and its limits

## Style

British-neutral professional English, no emoji, no hype, tables over prose when
carrying more than three facts, uncertainty stated plainly with the command that
would remove it.
