---
mode: agent
description: Validate the generated diagrams, write the Step01 architecture commentary, and add a missing sequence diagram for a named flow using only parsed activities.
tools: ['codebase', 'terminal']
---

# Step 01 — validate and enrich the architecture diagrams

Confirm that every generated diagram renders and that every element in it is traceable to a
parsed artefact, then write the commentary slot in
`${input:outputDir:analysis_output}/reports/Step01_ARCHITECTURE_DIAGRAMS_REPORT.md`.

**Optional input** — flow to add a sequence diagram for:
`${input:flowName:MainCreditProcess}`

## Procedure

1. **Regenerate the diagram sources** so the report and the standalone files agree.

   ```bash
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} \
     diagrams --format both
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} report
   ```

   Expected layout under `${input:outputDir:analysis_output}/generated_diagrams/`:

   | Path | Content |
   |---|---|
   | `mermaid/architecture-flows/system-context.mmd` | System context |
   | `mermaid/architecture-flows/process-dependencies.mmd` | Process dependency graph |
   | `mermaid/architecture-flows/integration-surface.mmd` | Integration surface |
   | `mermaid/architecture-flows/process-<slug>.mmd` | Per-process flow (top processes by complexity) |
   | `mermaid/component-diagrams/module-containers.mmd` | Container view |
   | `mermaid/component-diagrams/components.mmd` | Component view |
   | `mermaid/data-flow-diagrams/schema-usage-map.mmd` | Schema usage map |
   | `mermaid/er-diagrams/canonical-data-model.mmd` | Canonical data model |
   | `plantuml/c4-models/{context,container,component}.puml` | C4 views |
   | `plantuml/deployment-diagrams/topology.puml` | Deployment topology |
   | `plantuml/sequence-diagrams/sequence-<slug>.puml` | Per-process sequence |

2. **Validate each Mermaid source.** For every `.mmd` file check:

   - it opens with a valid graph directive (`graph`/`flowchart`, `erDiagram`, `sequenceDiagram`);
   - node ids are alphanumeric and labels containing spaces, brackets, slashes or colons are
     quoted;
   - no unbalanced brackets and no edge referencing an undeclared node;
   - subgraph blocks are closed.

   Record every file as PASS or FAIL with the reason. Report syntax defects rather than
   silently rewriting a generated file — the fix belongs in `tools/tibco_analyzer/diagrams/`.

3. **Validate each PlantUML source** against the offline-safe rules:

   - `@startuml` / `@enduml` present and matched;
   - **no `!theme`, no `!include`, no `!includeurl`**, no remote sprite or C4 macro fetch;
   - no orphan `note top :` — every note is attached to a declared element or uses
     `note over <alias>`;
   - every participant/alias referenced in an arrow is declared.

   If a rendering toolchain is available, confirm with `plantuml -checkonly <file>.puml`;
   otherwise state that validation was syntactic only.

4. **Trace elements to artefacts.** Take the system context, container and component diagrams
   and check that each drawn element exists in the graph:

   ```bash
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} \
     search "<element name>" --top 3 --json
   ```

   Anything drawn that is not a node — other than a grouping box or a legend — is a defect.
   Report it; do not paper over it. Unresolved targets must appear as **ExternalReference**.

5. **Add a sequence diagram for `${input:flowName:MainCreditProcess}` if one is missing.**

   First check whether `plantuml/sequence-diagrams/sequence-<slug>.puml` already exists. If it
   does, validate it and move on. If it does not, build one from the parsed facts only:

   ```bash
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} \
     search "${input:flowName:MainCreditProcess}" --label BWProcess --top 3
   cat ${input:outputDir:analysis_output}/context/processes/${input:flowName:MainCreditProcess}.md
   ```

   The per-process context pack gives the activities in execution order, the control flow
   (transitions, including error transitions), the schemas used and the shared resources. Draw
   **only** those. Participants are: the entry-point caller (typed from `entryType`), the
   process itself, each called process, and each external system reached through an adapter or
   shared resource. Each message is a parsed activity or transition — never an invented step
   such as "validate token" or "log audit event" unless an activity of that name exists.

   Write it as Mermaid (`sequenceDiagram`) into
   `${input:outputDir:analysis_output}/generated_diagrams/mermaid/architecture-flows/sequence-<slug>.mmd`
   and note in your report that it is hand-derived from the context pack rather than emitted by
   `diagrams`, so it will not be regenerated.

6. **Write Section 10, "Architecture Commentary"** — the `<!-- LLM: … -->` slot in the Step01
   report. Cover, referencing only components drawn in Sections 2-9:

   - coupling patterns visible in the dependency graph (which processes are hubs, which schemas
     are shared, with the degree counts from `context/complexity.md` hotspots);
   - layering violations — cross-module calls that bypass the expected direction, taken from the
     cross-module dependency table in `context/project-facts.md`;
   - candidate Spring Boot service boundaries, each justified by a cluster visible in the
     container or component view;
   - which flows deserve a full sequence diagram in the design phase, and why (entry point,
     branch count, external calls).

7. **Update Section 1's validation table only if a check failed.** The scaffold asserts
   "Assumed/placeholder components: 0" and "Remote PlantUML includes: 0". If your validation
   contradicts either, do not edit the table — report the contradiction as a parser defect.

## Acceptance criteria

- Every generated diagram file has an explicit PASS or FAIL verdict with a reason.
- No PlantUML file contains `!theme`, `!include`, `!includeurl` or an orphan `note top :`.
- Every element named in the commentary appears in a diagram in the same report.
- Any new sequence diagram uses only activities, transitions, called processes and systems
  present in the process context pack.
- Only the Section 10 slot changed in the report body.

## Do not

- Do not hand-edit generated `.mmd` or `.puml` files to fix a systematic defect — report it.
- Do not add a component, queue, database or external system that the graph does not contain.
- Do not infer layering ("this is the service layer") that the edges do not show.
- Do not use C4-PlantUML macros or any remote include.
- Do not describe deployment topology beyond what `plantuml/deployment-diagrams/topology.puml`
  already draws.
