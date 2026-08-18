---
mode: agent
description: Run the full deterministic analysis pipeline on a TIBCO BusinessWorks project and report what was produced and whether the graph validates.
tools: ['codebase', 'terminal']
---

# Bootstrap: analyse a new TIBCO project

Bring a previously unanalysed TIBCO BusinessWorks project to the point where every other prompt
in this repository can run against it. Produce no narrative analysis here — only the artefacts
and an honest statement of the pipeline's status.

**Inputs**

- TIBCO source root: `${input:tibcoPath:/path/to/tibco_code}`
- Output directory: `${input:outputDir:analysis_output}`

## Procedure

1. **Confirm the source tree exists** and note what is in it.

   ```bash
   ls -1 ${input:tibcoPath:/path/to/tibco_code}
   ```

   If the path does not exist, stop and ask for the correct one. Do not analyse a guess.

2. **Choose an invocation form.** From the repository root, either:

   ```bash
   PYTHONPATH=tools python -m tibco_analyzer --help
   ```

   or, if you prefer the console script:

   ```bash
   pip install -e . && tibco-analyze --help
   ```

   Use the same form for every step below. The examples use form A.

3. **Build the knowledge graph.**

   ```bash
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} \
     analyze --source ${input:tibcoPath:/path/to/tibco_code}
   ```

   Expected: a summary block printing total nodes, total relationships, node counts by label
   and relationship counts by type, plus `graph.json`, `neo4j_nodes.csv`,
   `neo4j_relationships.csv`, `neo4j_import.cypher`, `analysis_summary.json`,
   `analysis_queries.cypher` and `ANALYSIS_QUERIES.md`.

4. **Validate the graph. This is the gate.**

   ```bash
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} validate
   ```

   Expected: `Validation: PASS|WARN|FAIL (errors=N, warnings=N)` and
   `validation_report.md` / `.json`. Exit code 2 means FAIL.

   - **FAIL** — stop the pipeline. Quote the failing rules and their details from
     `validation_report.md`, and report that no downstream artefact should be trusted.
   - **WARN** — continue, but list every warning verbatim in your final report.

5. **Build the search index.**

   ```bash
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} index
   ```

   The command prints a JSON block including `vectorSearch`. If it is `false`, the index is
   lexical-only (BM25) — say so; do not claim semantic search is available. Re-run with
   `index --no-embeddings` if no embedding provider is installed and you want to skip the probe,
   or with `--provider sentence-transformers|openai|azure-openai` to force one.

6. **Generate diagrams.**

   ```bash
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} \
     diagrams --format both
   ```

   Expected: sources under `${input:outputDir:analysis_output}/generated_diagrams/` in
   `mermaid/architecture-flows/`, `mermaid/component-diagrams/`, `mermaid/data-flow-diagrams/`,
   `mermaid/er-diagrams/`, `plantuml/c4-models/`, `plantuml/deployment-diagrams/`,
   `plantuml/sequence-diagrams/`, plus a `README.md` index.

7. **Write the context packs.**

   ```bash
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} context
   ```

   Expected: `context/project-facts.md`, `entry-points.md`, `complexity.md`, `dead-code.md`,
   `integration-surface.md`, `data-contracts.md`, `migration-sequence.md`,
   `processes/<Name>.md`, `facts.json`, `MANIFEST.md`.

8. **Scaffold the step reports.**

   ```bash
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} report
   ```

   Expected: `reports/Step00_TIBCO_ANALYSIS_REPORT.md`,
   `reports/Step01_ARCHITECTURE_DIAGRAMS_REPORT.md`,
   `reports/Step02_DISCOVER_AND_BASELINE_REPORT.md`, `reports/inventory.json`. The reports
   contain `<!-- LLM: … -->` slots — leave them for the Step00/01/02 prompts.

   Steps 3-8 can be run in one shot with
   `... all --source ${input:tibcoPath:/path/to/tibco_code}`; prefer the individual
   commands when you need to react to a validation failure.

9. **Smoke-test the query surface** with one search and one impact run, using a real artefact
   name taken from `context/entry-points.md` or `context/data-contracts.md`:

   ```bash
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} \
     search "entry point" --top 5
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} \
     impact --target "<Label>:<Name>" --depth 3
   ```

## Report back

A short status note containing:

| Item | Content |
|---|---|
| Source root | The path analysed |
| Graph size | Nodes and relationships, copied from the `analyze` output |
| Node counts | The label table, copied verbatim |
| Validation | PASS / WARN / FAIL, error and warning counts, every non-INFO finding |
| Search index | Lexical-only or lexical + vector, with the provider reported by `index` |
| Diagrams | Count of sources written and the directories they landed in |
| Context packs | Count and the list of pack names |
| Reports | The three report paths and the number of `<!-- LLM: … -->` slots still pending |
| Next steps | Which prompt to run next (`graph-analysis`, then `architecture-diagrams`, then `discover-baseline`) |

## Acceptance criteria

- Every number in the report is copied from command output, not estimated.
- Validation status is stated explicitly, including WARN.
- Every path mentioned exists on disk (verify with `ls` if in doubt).
- No narrative conclusions about the estate — that is Step00's job.

## Do not

- Do not summarise the architecture, name risks, or rank complexity in this prompt.
- Do not fill any `<!-- LLM: … -->` slot.
- Do not continue past a FAIL validation.
- Do not read the TIBCO XML directly to describe the project.
- Do not invent flags. The full CLI surface is in `.github/copilot-instructions.md`.
