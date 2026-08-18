---
name: oracle-analyst
description: Analyse an Oracle PL/SQL estate held in a repository with this repository's deterministic analyzer — use when asked to analyse Oracle source (packages, package bodies, procedures, functions, triggers, views, DDL), build or query a Neo4j knowledge graph of a PL/SQL codebase, work out the blast radius of changing a table, column, package or procedure, trace which units read or write a table, produce column and table data lineage, find dead PL/SQL or unreferenced objects, review PL/SQL security and SQL performance, or scope an Oracle modernisation.
---

# Oracle PL/SQL analysis

## What this skill is for

The repository ships a two-layer solution:

| Layer | What it does | Who owns it |
|---|---|---|
| 1 — deterministic | `tools/oracle_analyzer` parses the source tree into a knowledge graph (`graph.json`), Neo4j exports, an inventory, context packs, diagrams, rule findings and report scaffolds | The Python CLI |
| 2 — narrative | Explains, prioritises and writes up those facts | You |

Use it when the question is about an existing Oracle PL/SQL estate: inventory,
dependencies, call graph, data lineage, security posture, SQL performance, dead
code, change impact or modernisation scope.

Do not use it to write new PL/SQL, to tune a running database, or to answer
questions about an APEX application — that is the `apex-analyst` skill, which
shares this graph vocabulary but parses a different artefact.

## The rule that is not negotiable

**Deterministic first. The analyzer produces facts; you produce meaning.**

1. If `analysis_output_oracle/graph.json` does not exist, you have no facts. Run
   `analyze`, or say plainly that the analysis has not been run.
2. Never state a count, a package, a dependency, a table or a risk you cannot point
   at in analyzer output.
3. Reading a `.pkb` to count procedures, guess a caller or infer a dependency is a
   defect, not diligence. Open a source file only to *confirm* something a command
   already surfaced, or to quote a line the graph does not model.
4. Always state coverage before claiming completeness. `graph.meta.coverage` reports
   `resolutionCoverage` and `callResolution`; below 80 % the graph is provisional and
   you must say so.
5. **Never call a unit dead without checking the dynamic-SQL list first.** A call
   assembled at runtime is invisible to this analysis by design, and that is
   recorded, not hidden.

## Invocation

From the repository root (Python 3.9+, no third-party packages needed):

```bash
# no install
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle <subcommand>

# installed
pip install -e . && oracle-analyze -o analysis_output_oracle <subcommand>
```

Before answering any analysis question:

```bash
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle analyze \
  --source <repo_root> --schema <OWNER> [--db-meta db_meta.json]
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle validate
```

`analyze` is the only command that reads the source tree; everything else reads
`analysis_output_oracle/graph.json`. If validation reports FAIL, stop — say the graph
is not trustworthy and quote the failing rules.

`--schema` sets the owner for unqualified objects. Getting it wrong scatters one
schema across several `DbSchema` nodes and depresses resolution; check the schemas
list in the inventory if the figure looks low.

## Where the answers already are

| Question | Route |
|---|---|
| Size, schemas, coverage | `analysis_output_oracle/context/estate-facts.md` |
| Every package, spec and body status | `context/packages.md` |
| What the outside world can call | `context/entry-points.md` |
| Which unit reads or writes which table | `context/data-access.md` |
| Hardest units to move | `context/complexity.md` |
| Rule findings with evidence | `context/findings.md` — or `oracle-analyze rules` |
| What nothing references | `context/dead-code.md` |
| What the graph could not resolve | `context/unresolved.md` |
| The whole inventory, machine-readable | `context/facts.json` or `inventory.json` |
| "What breaks if I change X?" | `oracle-analyze impact --target "DbTable:ORDERS"` |
| "Where does this table's data come from?" | `oracle-analyze lineage --target "DbTable:ORDERS"` |

## Task playbooks

### Understand an estate
1. `analyze`, `validate`, `inventory`, `context`, `report`.
2. Read `context/estate-facts.md` and `reports/Step00_ORACLE_INVENTORY_REPORT.md`.
3. Answer from the tables. Quote node ids (`db:ORDER_APP.CUSTOMER_PKG.CREATE_CUSTOMER`).

### Impact of a schema change
1. `oracle-analyze impact --target "DbTable:ORDERS" --direction upstream`.
2. Report the entry points first — published spec units, standalone units and
   triggers are what the outside world calls — then the private units behind them.
3. Every claim carries its hop count from the report; do not round it into "widely
   used".

### Data lineage
1. `oracle-analyze lineage --target "DbTable:ORDERS"`.
2. "Written by" is the provenance of the data; "Read by" is who is affected by it.
3. Name the views built on the table and the triggers that fire on it: both are
   control flow a caller never mentions.

### Security review
1. `oracle-analyze rules --category SECURITY`.
2. `SEC-001` (dynamic SQL) is first and is never a style comment: it is both an
   injection surface and the reason the dependency graph is incomplete there.
3. Cross-read `context/unresolved.md` — an unresolved reference near a finding means
   the true reach is larger than reported.

### SQL performance review
1. `oracle-analyze rules --category PERFORMANCE`.
2. Read the offending `:SqlStatement` node's properties — `hasSelectStar`, `hasHint`,
   `hasNoWhere`, `joinCount`, `tableCount` — from `context/data-access.md`.
3. Recommend against the specific statement, naming the unit that executes it.

### Modernisation scoping
1. Use `complexity`, `tier` and `fanIn` from `context/complexity.md` and the hotspots
   table.
2. Sequence by tier and by shared dependency: a unit reaching a high-`fanIn` table
   cannot move alone.
3. A `PackageSpec` change breaks every caller; the same change to a `PackageBody`
   does not. Say which one a proposal requires.

## Sibling chat modes

Two of the playbooks above have a dedicated chat mode with stricter refusal
conditions; switch to it rather than working freehand:

| Chat mode | Use it when |
|---|---|
| `oracle-impact` | the question is "what breaks if this changes" — it enforces resolving the target to a node, running `impact`, and stating what the analysis cannot see |
| `oracle-diagrammer` | the answer is a diagram — it enforces that every box and arrow traces to a node and an edge, and refuses invented infrastructure |

## Reference guides

- [graph-model.md](references/graph-model.md) — labels, relationships, ids, provenance
- [cypher-cookbook.md](references/cypher-cookbook.md) — the queries and when to use them
- [rule-catalogue.md](references/rule-catalogue.md) — every rule, what triggers it
- [resolution-limits.md](references/resolution-limits.md) — how source becomes edges, and where it stops
- [data-lineage.md](references/data-lineage.md) — reading lineage without overstating it

## Style

British-neutral professional English, no emoji, no hype, tables over prose when
carrying more than three facts, uncertainty stated plainly with the command that
would remove it.
