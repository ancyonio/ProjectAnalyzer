# Impact analysis reference

`impact` answers one question: *if this artefact changes, what else is affected, and
what must be re-tested?*

```bash
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output \
  impact --target "XSD:CreditResponse" --depth 4 --direction upstream
```

## How the blast radius is computed

### Target resolution

`--target` accepts, in order of precedence: a node id (`xsd_0002`), a `Label:Name`
pair, an exact name, a file path, a path suffix, then a case-insensitive partial name
match. `--target` is repeatable — several targets are analysed as one change set.

Resolution deliberately fails loudly. If a reference matches more than one node the
command prints every candidate with its label, id and file path and exits 1. Resolve
it with `--label`, with the node id, or with `--all-matches` if the union genuinely is
the question. Never guess which candidate was meant.

### Weighted best-first traversal

From each target the engine performs a best-first search over the graph, keeping for
every reached node the **strongest** path found rather than the shortest:

```
weight(next) = weight(current) x relationshipWeight x decay      decay = 0.75
```

Relationship weights are listed in `graph-model.md`. In summary: schema and contract
edges (`USES_XSD`, `USES_WSDL`, `IMPORTS_SCHEMA`) propagate at 1.0, sub-process calls
at 0.9, `CONTAINS` at 0.9, `EXECUTES` at 0.8, `EXPOSES` at 0.8, `REFERENCES` and
`DEPENDS_ON` at 0.7, configuration and connection edges at 0.6, `CALLS_EXTERNAL` and
`HANDLES_ERROR` at 0.5, `TRANSITIONS_TO` and `HAS_GROUP` at 0.4.

Three things terminate expansion:

| Limit | Value | Effect |
|-------|-------|--------|
| Depth | `--depth`, default 4 | Nodes at the depth limit are reported but not expanded |
| Weight floor | 0.01 | Paths decayed below this are dropped as noise |
| Excluded edges | `BELONGS_TO` always, plus `--exclude-rel` | Never traversed |

`BELONGS_TO` is excluded unconditionally: following module membership would drag
every artefact of a module into every result and destroy the signal.

`--include-rel TYPE` (repeatable) restricts traversal to the listed edge types, which
is how you get a contract-only view:

```bash
impact --target "XSD:Common" --include-rel USES_XSD --include-rel IMPORTS_SCHEMA
```

### Direction semantics

| `--direction` | Follows | Answers |
|---------------|---------|---------|
| `upstream` (default) | Incoming edges | Who depends on the target — **this is the blast radius** |
| `downstream` | Outgoing edges | What the target depends on — the scope needed to migrate it |
| `both` | Union of the two | Full neighbourhood; noisier, use sparingly |

Use `upstream` for change-risk questions and `downstream` for migration-scope
questions. Stating which one you ran is part of the finding: the same target gives
entirely different answers under each.

### Risk score and bands

```
riskScore = Σ (pathWeight x labelMultiplier) + 6.0 x affectedEntryPoints
```

| Label | Multiplier | Label | Multiplier |
|-------|-----------|-------|-----------|
| BWProcess | 3.0 | GlobalVariable | 1.0 |
| Service | 3.0 | Module | 1.0 |
| XSD | 2.0 | DataTransformation | 1.0 |
| SharedResource | 1.5 | Activity | 0.6 |
| Element | 0.5 | ErrorHandler | 0.4 |
| anything else | 1.0 | | |

| Band | Score |
|------|-------|
| CRITICAL | > 60 |
| HIGH | > 30 |
| MEDIUM | > 12 |
| LOW | ≤ 12 |

The score is deterministic and comparable across runs on the same graph. It is **not**
calibrated to any absolute scale. Use it to rank candidate changes against each other
and to gate CI; never present it as a probability, a severity or an effort figure.
Each affected entry point adds a flat 6.0, so a single externally visible surface can
move a small change out of LOW on its own — which is the intended behaviour.

### Affected entry points and test scope

An affected entry point is an impacted `BWProcess` whose `entryType` is not `NONE`.
These are the surfaces on which a regression becomes externally visible, and they are
the most important part of the output.

`testScope` derives directly from the impacted set:

| Field | Contents |
|-------|----------|
| `contractTests` | Every affected entry point — run parity tests against recorded production payloads |
| `processRegression` | Every impacted `BWProcess` |
| `schemaMarshallingTests` | Every impacted `XSD` |
| `serviceContractTests` | Every impacted `Service` |
| `recommendation` | Parity-test guidance, or a statement that no external surface is reached |

### Output artefacts

Default output is Markdown on stdout (impacted table truncated at 60 rows).
`--json` prints the full structured result including `via` paths and `parent` links.
`--save <stem>` writes three files: `<stem>.md`, `<stem>.json` and `<stem>.mmd` — the
last a Mermaid flowchart of the blast radius, capped at 40 nodes, with the target in
red and affected entry points in blue.

Every result also embeds an **equivalent Cypher** query, so a reader with the graph in
Neo4j can reproduce the traversal independently.

`--fail-on MEDIUM|HIGH|CRITICAL` exits 2 when the band reaches the threshold. This is
the CI gate for pull requests that touch shared artefacts.

## Choosing depth and direction

| Situation | Depth | Direction |
|-----------|-------|-----------|
| Schema or WSDL field change | 3–4 | upstream |
| Retiring or rewriting a sub-process | 3–4 | upstream |
| Changing a global variable or connection resource | 2–3 | upstream |
| Scoping the migration of one process | 2–3 | downstream |
| Investigating an unexpected coupling | 5–6, then narrow | both |

Depth 4 is the default because the common chain — schema → process → calling activity
→ calling process → entry point — is four hops. Going deeper rarely adds signal:
weights decay by 0.75 per hop, so a fourth-hop `TRANSITIONS_TO` tail already scores
around 0.02 and contributes almost nothing to the score. If a result is unreadably
large, reduce depth before anything else.

## Reading the result

1. **Risk band and affected entry points first.** Zero entry points means the change
   is internal; the conversation is about regression scope, not customer impact.
2. **Hop 1–2 rows are the real dependants.** Quote these by name with their node ids.
3. **The `via` path explains *why* each row is affected.** `<-[USES_XSD]-` is a direct
   consumer; `<-[CALLS]- <-[TRANSITIONS_TO]-` is an activity that merely sits
   downstream of the caller in the control flow — much weaker.
4. **The long tail is context, not findings.** Do not list 40 rows in a summary.
5. **Test scope is the deliverable.** A change-impact answer that does not say what to
   re-test is incomplete.

## Worked example 1 — schema change

**Change:** modify `CreditResponse.xsd`.

```bash
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output \
  impact --target "XSD:CreditResponse" --depth 4 --direction upstream
```

**Result (bundled sample project):** risk band MEDIUM (score 28.76), 11 impacted
artefacts, 3 affected entry points across 2 modules.

| Entry point | Type | Module | Hops |
|---|---|---|---|
| MainCreditProcess | HTTP_RECEIVER | CreditApp.module | 1 |
| NightlyArchiveProcess | TIMER | CreditApp.module | 1 |
| CustomerLookupProcess | JMS_RECEIVER | CustomerCore.module | 3 |

Direct consumers at hop 1, weight 0.75: `MainCreditProcess` (`bwp_0002`),
`NightlyArchiveProcess`, `ScoreCalculationProcess` (all `<-[USES_XSD]-`) and
`CreditService` (`<-[IMPORTS_SCHEMA]-`). The hop 3–4 activity rows (weights 0.15 and
0.05) are control-flow neighbours, not consumers.

**Write-up.** Changing `CreditResponse` reaches three externally visible surfaces
across two modules, including a synchronous HTTP endpoint and a JMS consumer, so the
change cannot be treated as internal. `CreditService` imports the schema, so the WSDL
contract changes with it. Required scope: parity tests on all three entry points with
recorded payloads, regression on the four listed processes, and a service contract
test for `CreditService`. The cross-module reach (`CustomerCore.module` at hop 3)
means the change needs coordination between two teams.

## Worked example 2 — shared sub-process change

**Change:** rewrite `ScoreCalculationProcess`.

```bash
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output \
  impact --target "BWProcess:ScoreCalculationProcess" --depth 4 --direction upstream
```

**Result:** risk band MEDIUM (score 17.37), 10 impacted artefacts, 2 affected entry
points. Hop 1 is the two calling activities (`CallScoreCalculation`,
`InvokeCreditCheck`, weight 0.675 via `<-[CALLS]-`) plus `CreditService` via
`<-[EXPOSES]-`; hop 2 is the two calling processes, `MainCreditProcess`
(HTTP_RECEIVER) and `CustomerLookupProcess` (JMS_RECEIVER).

**Write-up.** The process is a shared component with two independent callers in two
modules, one synchronous and one asynchronous. Behavioural changes are therefore not
locally testable: both entry points need parity tests. The `<-[EXPOSES]-` edge to
`CreditService` is inferred from a shared target namespace — verify it against the
WSDL before quoting it as a contract dependency.

Note the contrast with example 1: fewer impacted artefacts, but the score is lower
mostly because one fewer entry point is reached. When comparing two candidate changes,
compare the entry-point counts before the scores.

## Worked example 3 — global variable change

**Change:** repoint `ExperianServiceUrl`.

```bash
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output \
  impact --target "GlobalVariable:ExperianServiceUrl" --depth 3 --direction upstream
```

**Result:** risk band LOW (score 8.16), 2 impacted artefacts, 1 affected entry point —
`MainCreditProcess` at hop 1 via `<-[CONFIGURED_BY]-`, then `CreditService` at hop 2.

**Write-up.** Exactly one process interpolates this variable, so the configuration
change is narrow: it becomes a single `application.yml` property in the target
service, and only the HTTP endpoint needs a smoke test against the new URL.

Two caveats belong in this write-up. First, `CONFIGURED_BY` edges come from a textual
scan for `%%ExperianServiceUrl%%` in process XML, so a reference that exists only in a
deployment descriptor is invisible here. Second, the value itself is an external
dependency: the analysis says who reads the variable, not whether the new endpoint
behaves identically.

## Limits of the analysis

State these whenever a result carries weight. They are properties of the method, not
caveats to be buried.

- **Nothing outside the scanned tree exists.** Consumers in another repository,
  another BW domain, or a client application are invisible. Unresolved sub-process
  targets appear as `ExternalReference` nodes reached by `CALLS_EXTERNAL` — treat each
  as an open scope question.
- **No runtime configuration.** Deployment descriptors, EAR-level property overrides,
  environment-specific substitution files outside the scanned tree, and load-balancer
  or gateway routing are not modelled. A variable with no `CONFIGURED_BY` edge is
  "not referenced in process XML", not "unused".
- **No data-level coupling.** Two processes writing to the same database table, the
  same JMS destination or the same file share nothing in this graph unless they share
  a schema or a resource. Database and file-level coupling must be reviewed manually.
- **No runtime behaviour.** The graph is static structure. It cannot tell you whether
  a branch is ever taken, how often a path executes, or what the latency budget is.
- **Inferred edges are labelled.** `EXPOSES` with `evidence: shared-target-namespace`
  and `CONFIGURED_BY` from `%%Var%%` scanning are evidence-based inferences; check the
  property before presenting them as declarations.
- **Weights are heuristics.** The relationship weights and label multipliers encode
  judgement about how change propagates. They are consistent and reproducible, not
  measured. Two changes with similar scores are not distinguishable by score alone —
  compare their affected entry points and hop-1 dependants instead.
