# Diagram standards

Diagrams are generated, not drawn:

```bash
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output diagrams --format both
```

Every node and every edge in the generated sources comes from a parsed artefact.
That property is the whole point — a TIBCO architecture diagram containing an assumed
API gateway or a placeholder cache is worse than no diagram, because it will be
believed.

## Which diagram answers which question

| Question | Diagram | File |
|----------|---------|------|
| What does this estate expose, and to whom? | System context | `mermaid/architecture-flows/system-context.mmd`, `plantuml/c4-models/context.puml` |
| How is it partitioned, and how coupled are the parts? | Container / module view | `mermaid/component-diagrams/module-containers.mmd`, `plantuml/c4-models/container.puml` |
| What are the components inside, and what do they use? | Component view | `mermaid/component-diagrams/components.mmd`, `plantuml/c4-models/component.puml` |
| Which process calls which? | Process dependency graph | `mermaid/architecture-flows/process-dependencies.mmd` |
| How does one process actually work? | Process flow (activities and transitions) | `mermaid/architecture-flows/process-<name>.mmd` |
| What happens at runtime for one request? | Sequence view | `plantuml/sequence-diagrams/sequence-<name>.puml` |
| Which schemas must be frozen, and who consumes them? | Schema usage map | `mermaid/data-flow-diagrams/schema-usage-map.mmd` |
| What is the canonical data model? | ER view | `mermaid/er-diagrams/canonical-data-model.mmd` |
| What do we integrate with? | Integration surface | `mermaid/architecture-flows/integration-surface.mmd` |
| Where does it run and what does it talk to? | Deployment topology | `plantuml/deployment-diagrams/topology.puml` |
| What breaks if we change X? | Blast radius | `impact --save <stem>` → `<stem>.mmd` |

Pick the smallest view that answers the question. A whole-estate component map is
almost never the right answer to a question about one flow.

## Mermaid or PlantUML

| Use Mermaid when | Use PlantUML when |
|------------------|-------------------|
| The diagram goes into Markdown — reports, pull requests, README files | The diagram is a C4-style architecture deliverable |
| The audience renders in GitHub or VS Code with no toolchain | You need a runtime sequence with participants and activation bars |
| The view is a flow, dependency graph, schema map or ER model | The view is a deployment topology |

Both formats are generated from the same graph, so they never disagree. Mermaid is
the default for anything embedded in a report; the Step01 report embeds Mermaid only.

Rendering: Mermaid renders natively in GitHub, in VS Code with a Mermaid preview
extension, or at mermaid.live. PlantUML renders with a local install
(`plantuml -tsvg <file>.puml`) or the VS Code PlantUML extension pointed at a local
server. No generated file requires network access to render.

## Forbidden PlantUML directives

These break offline rendering or produce silent syntax failures. The generator never
emits them, and neither should a hand-written supplement.

| Forbidden | Why | Use instead |
|-----------|-----|-------------|
| `!theme <name>` | Resolves against a remote theme repository; fails or hangs on an offline server | Explicit `skinparam` lines |
| `!include https://…` / `!includeurl` | Requires network access; C4-PlantUML macros (`!include C4_Container.puml`) are the usual offender | Express C4 with plain `rectangle`, `package`, `component`, `database`, `node` and `<<stereotype>>` |
| `!include <local/path>` across repositories | Breaks when the file is rendered elsewhere | Keep each `.puml` self-contained |
| Orphan `note top : text` | A `note top` with no attached element is a parse error in several PlantUML versions | Attach it: `note right of ALIAS : text`, or use `title` |
| Unquoted labels containing `<`, `>`, `"` | Collide with stereotype and quoting syntax | Escape: `<`/`>` become `(`/`)`, `"` becomes `'` |

The standard header used by the generator, and the one a supplementary diagram should
copy:

```plantuml
@startuml
skinparam shadowing false
skinparam defaultFontName "Segoe UI"
skinparam componentStyle rectangle
skinparam wrapWidth 220

title <what this diagram shows>

' ... elements and relations ...

@enduml
```

Mermaid has its own escaping constraints, applied by the generator and required in
hand-written diagrams: node ids must match `[A-Za-z0-9_]`; label text must not contain
`"`, `<`, `>` or `|` (they become `'`, `(`, `)` and `/`); labels are truncated to
roughly 70 characters and contain no raw newlines — use `<br/>`.

## Naming and folder conventions

Everything lands under `<output>/generated_diagrams/` with a generated `README.md`
listing the files and their formats:

```
generated_diagrams/
├── README.md
├── mermaid/
│   ├── architecture-flows/      system-context, process-dependencies,
│   │                            integration-surface, process-<name>
│   ├── component-diagrams/      module-containers, components
│   ├── data-flow-diagrams/      schema-usage-map
│   └── er-diagrams/             canonical-data-model
└── plantuml/
    ├── c4-models/               context, container, component
    ├── deployment-diagrams/     topology
    └── sequence-diagrams/       sequence-<name>
```

Rules:

- Mermaid sources use `.mmd`; PlantUML sources use `.puml`.
- Per-process files are suffixed with the sanitised, lower-cased process name:
  `process-maincreditprocess.mmd`, `sequence-maincreditprocess.puml`.
- The directory is regenerated wholesale. **Never hand-edit a file under
  `generated_diagrams/`** — the next run overwrites it and the edit is silently lost.
  Put supplementary diagrams somewhere else and say where they came from.
- `--diagram-dir <path>` redirects the output if a different location is required.

Generation is bounded, and the bounds matter when you describe a diagram as complete:

| View | Cap |
|------|-----|
| Per-process flow diagrams (Mermaid) | Top 12 processes by complexity |
| Per-process sequence diagrams (PlantUML) | Top 8 processes by complexity |
| Component view | Top 60 processes (Mermaid), top 40 (PlantUML), by complexity |
| Schema usage map | 60 processes and 60 schemas |
| ER view | 15 schemas, 15 elements each |
| Context view | 12 processes per entry type, 8 consumers per shared resource |

If the estate exceeds a cap, say so: "the component view shows the 60 most complex
processes of N" is accurate; "the component view shows the estate" is not.

## Verification checklist

Run through this before presenting any diagram, generated or hand-written.

1. **Every element traces to a graph node.** For each box, name the node id or the
   file it came from. If you cannot, delete the box.
2. **Every arrow traces to a relationship.** `USES_XSD`, `CALLS`, `REFERENCES`,
   `CONNECTS_TO`, `TRANSITIONS_TO` — name the type. An arrow that means "probably
   talks to" does not belong.
3. **No assumed patterns.** No gateway, load balancer, cache, service registry,
   circuit breaker or database that the graph did not produce. TIBCO estates
   frequently lack all of these, and inventing them corrupts the migration plan.
4. **Synthetic nodes are described honestly.** `System` nodes are one per technology
   (`JDBC_System`, `JMS_System`), not named third parties. `Adapter` nodes are
   analyzer constructs representing a connection configuration.
5. **Mocks and placeholders are marked.** If a supplementary diagram must show a
   proposed target-state component, label it `[PROPOSED]` or `[NOT IN SOURCE]` in the
   element text itself, not only in the caption.
6. **Caps are disclosed.** State when a view is truncated (see the table above).
7. **Empty is a finding, not a failure.** `No inter-process calls detected` or
   `No shared resources detected` is real output. Report it; do not fill the gap.
8. **It renders.** Mermaid: paste into a preview. PlantUML: render locally. A diagram
   that does not render is not a deliverable.
9. **The source file is cited.** Give the path under `generated_diagrams/` so the
   reader can regenerate it.

## Hand-writing a supplementary diagram

Sometimes the generated set does not frame the question — for example, one end-to-end
flow spanning three processes, or a proposed target-state boundary. That is legitimate
provided the no-assumptions rule holds.

Procedure:

1. **Gather the facts first.** Open the relevant `context/processes/<Name>.md` packs
   and, if the diagram concerns coupling, run `impact --save` and use its `.mmd` as a
   starting point.
2. **Build an element list before drawing.** One line per element: label, name, node
   id, source file. If a line has no node id, it does not go in — or it goes in
   explicitly marked as proposed.
3. **Build an edge list the same way.** Source node, target node, relationship type,
   and where that relationship is recorded.
4. **Draw only from those two lists.** No element and no arrow may appear in the
   diagram that is not on them.
5. **Separate as-is from to-be.** Never mix source-derived and proposed elements in
   one undifferentiated diagram. Use a distinct subgraph or package titled
   `Proposed (not in source)`, and mark each proposed element in its own label.
6. **Store it outside `generated_diagrams/`** and state, in the surrounding text, which
   analyzer outputs it was derived from.
7. **Run the verification checklist** before presenting it.

Worked shape of the element list for a hand-written end-to-end flow:

| Element | Label | Node id | Source |
|---------|-------|---------|--------|
| MainCreditProcess | BWProcess | `bwp_0002` | `CreditApp.module/Processes/MainCreditProcess.process` |
| ScoreCalculationProcess | BWProcess | `bwp_0004` | `CreditApp.module/Processes/ScoreCalculationProcess.process` |
| CreditResponse | XSD | `xsd_0002` | `CreditApp.module/Schemas/CreditResponse.xsd` |
| CreditDB | SharedResource | `res_0002` | `CreditApp.module/Resources/CreditDB.sharedjdbc` |

and the corresponding edge list:

| From | To | Relationship | Evidence |
|------|----|--------------|----------|
| MainCreditProcess | ScoreCalculationProcess | `CALLS` (via `CallScoreCalculation`) | Process call edge in the graph |
| MainCreditProcess | CreditResponse | `USES_XSD` | Schema reference in the process |
| MainCreditProcess | CreditDB | `REFERENCES` | Shared-resource reference |

If a row cannot be filled in, the diagram is not ready.
