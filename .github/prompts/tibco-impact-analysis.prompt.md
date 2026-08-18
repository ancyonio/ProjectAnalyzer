---
mode: agent
description: Answer "what breaks if I change X?" — resolve the artefact, run the blast-radius analysis, interpret the risk band, and produce a reviewable change-impact note.
tools: ['codebase', 'terminal']
---

# Change-impact analysis (blast radius)

Produce a reviewable note stating what a change to one artefact will affect, which externally
visible surfaces regress, and what must be tested.

**Artefact under change:** `${input:artefact:XSD:CreditResponse}`
**Change being considered:** `${input:change:add an optional field to the response}`

## Procedure

1. **Resolve the artefact to exactly one node.** The `--target` flag accepts a node id
   (`bwp_0002`), an exact name, a `Label:Name` pair, or a file path.

   ```bash
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} \
     impact --target "${input:artefact:XSD:CreditResponse}" --depth 4
   ```

   - **"no artefact matches"** — the name is wrong. Find it:

     ```bash
     PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} \
       search "${input:artefact:XSD:CreditResponse}" --top 10
     ```

     Re-run `impact` with the node id from the search output.

   - **"Ambiguous target"** — the command lists the candidates with their labels, node ids and
     file paths. Disambiguate with `--label`, or with the node id. Use `--all-matches` only when
     the change genuinely affects every match, and say so in the note.

2. **Run the upstream analysis and save it.** Upstream answers "who depends on this" — that is
   the blast radius, and it is the default.

   ```bash
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} \
     impact --target "${input:artefact:XSD:CreditResponse}" \
     --depth 4 --direction upstream \
     --save ${input:outputDir:analysis_output}/impact/<slug>
   ```

   `--save` writes three files from one stem: `<slug>.md` (the report), `<slug>.json` (the same
   data), `<slug>.mmd` (a Mermaid blast-radius diagram). The report contains: targets,
   direction and depth, risk band and score, a summary table (impacted artefacts, affected entry
   points, affected modules), impacted-by-type counts, the affected entry-point table, the ranked
   impacted-artefact table with hops/weight/path, the required test scope, and an equivalent
   Cypher query.

3. **Tune the traversal only with reason, and state what you changed.**

   - `--depth` defaults to 4. Raise it to see distant callers; note that weight decays per hop,
     so far artefacts carry little weight. Lower it to isolate direct dependents.
   - `--include-rel` restricts traversal to given edge types — e.g. `--include-rel USES_XSD
     --include-rel IMPORTS_SCHEMA` for a pure contract-change view.
   - `--exclude-rel` drops noisy edges — e.g. `--exclude-rel TRANSITIONS_TO` to see structural
     dependency without intra-process control flow. `BELONGS_TO` is always excluded.

4. **Optionally run downstream** when the question includes "what does this artefact depend on"
   — for example when assessing whether the artefact can move first in a migration wave:

   ```bash
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} \
     impact --target "${input:artefact:XSD:CreditResponse}" --direction downstream --depth 3
   ```

   Keep the two directions separate in the note. Do not add their counts together.

5. **Interpret the risk band.** The band comes from a weighted score over impacted artefacts and
   affected entry points; report the band and the score as printed.

   | Band | Score | Reading |
   |---|---|---|
   | CRITICAL | > 60 | Broad blast radius across entry points and modules. Treat as a coordinated release; needs a contract-compatibility strategy and full regression. |
   | HIGH | > 30 | Several dependants including externally visible surfaces. Needs a staged rollout and parity tests per entry point. |
   | MEDIUM | > 12 | Contained, but external surfaces are touched. Targeted regression around the listed entry points. |
   | LOW | ≤ 12 | Local change. Process-level regression is usually sufficient. |

   The band is a computed heuristic, not a decision. Explain what actually drives it — the number
   of affected entry points, the modules crossed, the strongest coupling paths.

6. **List the affected entry points and required test scope** verbatim from the report. Entry
   points are the externally visible regressions: each one is a caller-facing surface that can
   break. For each, name the entry type and the hop count, and — from `context/entry-points.md`
   — its Spring Boot target.

7. **Confirm the top dependants.** Open the file of the two or three strongest-weight impacted
   artefacts and confirm the dependency is real (the schema is genuinely referenced, the process
   is genuinely called). A path that survives inspection is worth more in review than a table row.

8. **Write the change-impact note** (below), embedding the saved Mermaid diagram from
   `<slug>.mmd` in a ```mermaid block.

## Change-impact note format

````
# Change impact: <artefact>

**Change:** <what is being changed>
**Target:** <Label>:<Name> (node <id>, `<file path>`)
**Analysis:** impact --direction upstream --depth <N> [--include-rel …]
**Risk band:** <BAND> (score <S>)

## What breaks

| Impacted artefact | Type | Module | Hops | Path |
|---|---|---|---|---|

## Externally visible regressions

| Entry point | Type | Module | Hops | Spring Boot target |
|---|---|---|---|---|

## Required test scope

- Contract / parity tests: …
- Process regression: …

## Blast radius

```mermaid
<contents of <slug>.mmd>
```

## What this analysis cannot see

- Runtime configuration and substitution variables resolved at deployment time.
- Deployment descriptors, appspace/EAR configuration and anything outside the scanned tree.
- Behaviour of external systems reached through adapters or HTTP — a compatible schema change
  may still break a consumer that parses strictly.
- Consumers outside this repository: other applications binding to the same contract are
  invisible to the graph.
- Data volumes, latency and traffic mix.

## Recommendation

<Go / staged / hold, with the specific condition that changes the answer.>
````

## Acceptance criteria

- Exactly one resolved target (or an explicit `--all-matches` justification).
- Every table is copied from the `impact` output, not re-derived.
- The risk band is quoted with its score and explained by its drivers.
- The "cannot see" section is present, always.
- The saved `.md` / `.json` / `.mmd` files are referenced by path so a reviewer can re-check.

## Do not

- Do not estimate a blast radius without running `impact`.
- Do not merge upstream and downstream results into one count.
- Do not claim a change is safe because the band is LOW — say what was tested and what was not.
- Do not add artefacts to the impacted list from your own reading of the XML.
- Do not use `--fail-on` here; that flag is for CI gating, not for reporting.
