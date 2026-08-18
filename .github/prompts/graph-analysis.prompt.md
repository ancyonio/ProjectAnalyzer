---
mode: agent
description: Complete Step00 — write the executive summary and migration risk assessment strictly from the context packs, and add Neo4j import and verification instructions.
tools: ['codebase', 'terminal']
---

# Step 00 — complete the TIBCO graph analysis report

Fill the two narrative slots in `${input:outputDir:analysis_output}/reports/Step00_TIBCO_ANALYSIS_REPORT.md`
using only facts already computed by the analyzer.

## Preconditions

```bash
PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} validate
```

If the status is FAIL, stop and report the failing rules. A narrative built on an invalid graph
is worse than no narrative.

If `reports/Step00_TIBCO_ANALYSIS_REPORT.md` or `context/` is missing, regenerate:

```bash
PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} context
PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} report
```

## Procedure

1. **Read the ground truth, in this order.** Do not open TIBCO XML at any point in this prompt.

   | File | What you take from it |
   |---|---|
   | `context/project-facts.md` | Totals, node/relationship counts, artefact families, tier mix, module table, cross-module dependencies |
   | `context/complexity.md` | Process ranking, change hotspots, error-handling gaps, circular dependencies |
   | `context/dead-code.md` | Orphan schemas, unreachable processes, unused resources and transformations |
   | `context/entry-points.md` | Entry-point catalogue and Spring targets (for the dominant entry style) |
   | `context/migration-sequence.md` | Wave ordering, for the "recommended first wave" sentence |
   | `reports/Step00_TIBCO_ANALYSIS_REPORT.md` | Sections 2-9 and 11-12, already generated |

2. **Read the report scaffold** and locate the two slots:

   - Section 1 "Executive Summary" — `<!-- LLM: Summarise the estate in 5-8 sentences … -->`
   - Section 10 "Migration Risk Assessment" — `<!-- LLM: For each Critical/High tier process and each top-5 hotspot … -->`

3. **Write Section 1, Executive Summary.** 5-8 sentences, covering exactly:

   - estate size (nodes, relationships, processes, modules, schemas — with the numbers);
   - dominant entry-point style, with the count per type;
   - where complexity concentrates (tier distribution and the top two or three processes by score);
   - the top three migration risks, each traceable to a table in this report;
   - the recommended first wave, named from `context/migration-sequence.md`.

   Every count appears as a digit and matches the generated tables. No adjectives standing in
   for measurements ("large", "heavily coupled") unless the number is next to them.

4. **Write Section 10, Migration Risk Assessment.** A table, one row per Critical/High tier
   process and per top-5 hotspot, with no rows for artefacts absent from the report:

   | Artefact | Type | Evidence (section / metric) | Migration risk | Mitigation |
   |---|---|---|---|---|

   - "Evidence" cites the report section and the measured value, e.g.
     "§4 complexity 24.0, 10 activities, 2 schemas".
   - "Migration risk" is specific to the artefact: which contract, which caller, which
     integration. Not "may be complex".
   - "Mitigation" is an action a team can schedule.
   - Add a short paragraph beneath the table for circular dependencies and error-handling gaps
     if `context/complexity.md` lists any; state "none detected" if it does not.

5. **Verify Section 11, Neo4j Import & Verification.** The scaffold already carries the
   `neo4j-admin database import` block. Confirm the four referenced files exist:

   ```bash
   ls -1 ${input:outputDir:analysis_output}/neo4j_nodes.csv \
         ${input:outputDir:analysis_output}/neo4j_relationships.csv \
         ${input:outputDir:analysis_output}/neo4j_import.cypher \
         ${input:outputDir:analysis_output}/analysis_queries.cypher
   ```

   If — and only if — the section lacks the browser-based route, append it beneath the existing
   content without altering what is there:

   ```bash
   cypher-shell -u neo4j -p <password> -d tibco-migration \
     -f ${input:outputDir:analysis_output}/neo4j_import.cypher
   ```

   Then the two verification queries, whose expected results are the tables in Section 2:

   ```cypher
   MATCH (n) RETURN labels(n)[0] AS NodeType, count(n) AS Count ORDER BY Count DESC;
   MATCH ()-[r]->() RETURN type(r) AS RelationshipType, count(r) AS Count ORDER BY Count DESC;
   ```

   State that the import is verified when both result sets match Section 2 exactly.

6. **Update the readiness checklist rows** in Section 12 for the two narrative rows only:
   change `PENDING LLM` to `DONE` for "Risk narrative written" and "Executive summary written",
   and put the section number in the Evidence column. Touch no other row.

7. **Self-check against the anti-hallucination checklist** in `.github/copilot-instructions.md`
   §9. For each number you wrote, name the table it came from.

## Acceptance criteria

- Only the content beneath the two `<!-- LLM: … -->` markers changed, plus the two checklist
  rows in Section 12 and any appended Section 11 commands.
- The `<!-- LLM: … -->` markers themselves are still present.
- Every artefact named in Sections 1 and 10 appears in a generated table in the same report.
- Every count matches the generated tables digit for digit.
- No table, count or diagram generated by the analyzer was edited.

## Do not

- Do not read `.process`, `.xsd` or `.wsdl` files to enrich the narrative.
- Do not add sections, reorder them or renumber them.
- Do not estimate effort in person-days — no such measurement exists in the graph.
- Do not describe runtime behaviour, traffic volumes or deployment topology.
- Do not name a risk you cannot tie to a row in Sections 4, 6, 7 or 8.
