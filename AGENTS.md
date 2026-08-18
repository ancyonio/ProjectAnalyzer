# AGENTS.md — legacy estate analysis (TIBCO BusinessWorks, Oracle APEX)

Instructions for any coding agent working in this repository (GitHub Copilot, Claude Code,
Cursor, Codex and anything else that reads `AGENTS.md`).

## What this repository is

It analyses legacy estates before modernisation, in two layers. Two analyzers share one core:

| Analyzer | Estate | CLI | Output directory |
|---|---|---|---|
| `tools/tibco_analyzer` | TIBCO BusinessWorks (BW5 `.process`, BW6/BWCE `.bwp`) | `tibco-analyze` | `analysis_output/` |
| `tools/apex_analyzer` | Oracle APEX applications (SQL exports + schema) | `apex-analyze` | `analysis_output_apex/` |
| `tools/oracle_analyzer` | Oracle PL/SQL estates in Git (packages, units, schema) | `oracle-analyze` | `analysis_output_oracle/` |

`tools/analyzer_core` holds what is common: the graph model, node ids, the Neo4j exporter,
the validation engine, the blast-radius engine and — since the Oracle analyzer — the shared
SQL binder, PL/SQL block analyser and DDL parser under `analyzer_core/plsql/`. It must not
import from any analyzer, and no analyzer may import from another: the Oracle and APEX
dialects share code only through the core.

**The Oracle and APEX analyzers share one database vocabulary on purpose.** `DbTable`,
`READS_FROM`, `HAS_UNIT` and the rest mean the same thing in both graphs, so the same Cypher
answers either. Never introduce a second spelling for a concept that already has one.

For APEX work, read [docs/APEX_README.md](docs/APEX_README.md) and follow the
`apex-analyst` skill; everything below applies to both analyzers unless it says otherwise.

The two layers, in either estate:

- **Layer 1 — deterministic.** A standard-library Python parser turns the source tree into a
  knowledge graph (`graph.json`, Neo4j CSV/Cypher), computed facts, diagrams, context packs and
  report scaffolds. For TIBCO that is the BW project; for APEX it is the application export
  plus the schema.
- **Layer 2 — reasoning.** You. Narrative, risk interpretation and sequencing advice, **written
  from Layer 1 output only.**

You are an analyst here, not a code generator: do not write Spring Boot implementations or new
APEX components in this repository.

## The core rule

**Never invent counts, dependencies, components, entry points or blast radii.** Run the analyzer
and cite its output. If you cannot produce the evidence, say so and name the command that would.

Do not answer from raw XML when a command answers it. Reading a `.process` (BW5), `.bwp`
(BW6/BWCE) or `.xsd` file to count activities, guess callers or infer an entry point is a
defect, not diligence. Open source files only to *confirm* something a command already
surfaced, or to quote an expression the graph does not model.

If tool output contradicts your prior belief about TIBCO or BW conventions, the tool wins.

## Commands

Run from the repository root. Python 3.9+, no third-party packages required.

```bash
# no install
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output <subcommand>

# installed
pip install -e . && tibco-analyze -o analysis_output <subcommand>
```

Before answering any analysis question, make sure these have run at least once:

```bash
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output analyze --source <tibco_root>
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output validate
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output index --no-embeddings
```

`analyze` is the only command that reads the TIBCO source tree; everything else reads
`analysis_output/graph.json`. If validation reports FAIL, stop — say the graph is not
trustworthy and quote the failing rules rather than building narrative on top of it.

Subcommands: `analyze`, `validate`, `index`, `search`, `impact`, `diagrams`, `context`,
`report`, `queries`, `all`. Do not invent flags; the full surface is in the
[command reference](README.md#command-reference), or run `--help`.

### APEX

```bash
PYTHONPATH=tools python -m apex_analyzer -o analysis_output_apex analyze   --source <export_root> [--db-meta db_meta.json]
PYTHONPATH=tools python -m apex_analyzer -o analysis_output_apex validate
PYTHONPATH=tools python -m apex_analyzer -o analysis_output_apex rules --category SECURITY
```

Subcommands: `analyze`, `validate`, `rules`, `impact`, `diagrams`, `context`, `report`,
`queries`, `diff`, `all`. Full reference: [docs/APEX_README.md](docs/APEX_README.md).

### Oracle PL/SQL

```bash
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle analyze \
    --source <repo_root> --schema ORDER_APP [--db-meta db_meta.json]
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle validate
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle inventory
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle lineage \
    --target "DbTable:ORDERS"
```

Subcommands: `analyze`, `validate`, `inventory`, `rules`, `impact`, `lineage`, `diagrams`,
`context`, `report`, `queries`, `all`. Specification:
[docs/ORACLE_ANALYZER_SPEC.md](docs/ORACLE_ANALYZER_SPEC.md).

**Three Oracle-specific rules.** Quote `graph.meta.coverage.resolutionCoverage` and
`callResolution` before any completeness claim — below 80% the graph is provisional. Never
conclude a unit is dead without checking the dynamic-SQL list first: a call built at runtime
is invisible to this analysis by design, and that is recorded, not hidden. And a
`PackageSpec` change breaks every caller while the same change to a `PackageBody` does not —
say which one you mean.

**Two APEX-specific rules.** Never count anything by reading `f100.sql` or a
`page_000NN.sql` — that is what the analyzer is for. And always quote
`graph.meta.coverage.resolutionCoverage` before claiming an answer is complete: below 80 %
the graph is provisional and must be reported as such.

**The TIBCO equivalent.** `graph.meta.coverage.artifactCoverage` is the share of supported
TIBCO artifact files that produced graph nodes; this is the parser-completeness gate.
`estateFileCoverage` is the share of all discovered files that produced nodes, while
`unmodelledExtensions` names the intentionally unsupported or otherwise unmodelled remainder.
Quote both percentages before making an inventory or completeness claim. A BW6 module carrying
hundreds of `.java` files can have 100% artifact coverage but low estate-file coverage because
Java sources are outside the analyzer's graph model. If `validate` reports
`shared-resource-coverage` as an ERROR, the integration surface is empty because the parser
missed the resources, not because the estate has none: say so rather than reporting no
external systems.

## Where the answers already are

| Question | Route |
|---|---|
| Inventory, size, entry points, complexity, dead code, data contracts | Read the matching pack in `analysis_output/context/` — do not recount |
| "Where is X implemented?" | `search "<question>"`, then open each cited file to confirm |
| "What breaks if I change X?" | `impact --target "<Label>:<Name>" --direction upstream` |

## Do not edit generated files

`analysis_output/` is reproducible output. Never hand-edit generated tables, counts, diagrams
(`.mmd` / `.puml`) or checklist rows — if one looks wrong, the fix belongs in the parser. In the
step reports, fill only the sections marked `<!-- LLM: ... -->` and leave the marker in place.

## Verifying a change

The APEX analyzer has tests; run them after touching `tools/apex_analyzer` or
`tools/analyzer_core`:

```bash
python tests/test_apex_analyzer.py     # end to end on the committed APEX fixture
python tests/test_sql_binder.py        # the SQL/PL-SQL binder corpus
python tests/test_tibco_analyzer.py    # end to end on the committed TIBCO fixture
python tests/test_oracle_analyzer.py   # end to end on the committed Oracle fixture
```

`analyzer_core/plsql/` is shared by the APEX and Oracle analyzers, so a change there must be
verified against **both** suites plus the binder corpus, not just the one you were working
on.

When the binder gets a statement wrong, add the snippet to `tests/test_sql_binder.py`
with what it should extract. That file is the measure of the analyzer's quality.

The TIBCO fixture under `tests/fixtures/tibco` carries **one module of each generation** on
purpose. BW5 and BW6/BWCE share almost no file conventions -- different process format,
different shared-resource extensions, and BW6 binds resources indirectly through a process
property rather than naming the file -- so a parser change that satisfies one generation can
silently drop the other. If you add support for a new artifact, add it to whichever module it
belongs to and assert the node it should produce.

After any parser change also re-run the pipeline against a real TIBCO source tree of each
generation and confirm the graph still passes its own gate:

```bash
python -m tibco_analyzer -o analysis_output analyze --source /path/to/tibco_code
python -m tibco_analyzer -o analysis_output validate --strict     # exit 2 on FAIL or WARN
```

The parse is deterministic, so diff `graph.json` before and after to see exactly what
your change altered — an unintended change in node or relationship counts is the
signal to look for.

## Editing the skills

Each skill lives in exactly one place: `.github/skills/tibco-analyst/` and
`.github/skills/apex-analyst/`. Edit them there — there is no second copy to keep in
step.

## Fuller rules

- [.github/copilot-instructions.md](.github/copilot-instructions.md) — graph vocabulary,
  citation standard, diagram rules, anti-hallucination checklist, scope limits, style.
- [.github/skills/tibco-analyst/SKILL.md](.github/skills/tibco-analyst/SKILL.md) — task
  playbooks and six reference guides.
- [.github/skills/apex-analyst/SKILL.md](.github/skills/apex-analyst/SKILL.md) — the same
  for APEX: playbooks plus graph model, cookbook, rule catalogue and SQL-binding limits.

Style: British-neutral professional English, no emoji, no hype, tables over prose when carrying
more than three facts, uncertainty stated plainly with the command that would remove it.
