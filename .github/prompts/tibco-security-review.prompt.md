---
mode: agent
description: Review a TIBCO BusinessWorks estate's security and correctness posture from the deterministic rule findings.
---

# TIBCO BusinessWorks security review

## 1. Collect the findings

```bash
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output rules \
  --category SECURITY --json
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output rules \
  --category CORRECTNESS --min-severity HIGH
```

Then read `analysis_output/context/findings.md` for the whole set,
`context/integration-surface.md` for what is exposed, and `context/unresolved.md`
for the gaps — not only where a rule fired.

## 2. Rank

Order by severity, then by whether the artefact is reachable from outside the engine,
then by how much data it touches (`context/data-contracts.md`).

An integration estate inverts the usual priority. The highest-value finding is rarely
the most severe one in isolation — it is the one on an artefact that **crosses a
trust boundary**. A `MEDIUM` on a public-facing HTTP endpoint outranks a `HIGH` on a
process nothing can invoke.

`SEC-001` is first among the credential findings and needs care in how it is written
up. The parser records only that a credential is present, never its value, and TIBCO's
`#!` obfuscation is reversible but is never reversed here. **Report that a secret is
committed and where — never what it is**, and never reproduce the obfuscated string.

## 3. For each finding, report

| Field | From |
|---|---|
| What is wrong | the rule's `description` |
| Where | node id, `filePath`, the owning process |
| Why it matters here | what the artefact reaches — endpoint, queue, table, file |
| Fix | the linked `:Recommendation`, made specific to this artefact |

## 4. Cover what rules cannot

State these explicitly, from the context packs rather than from a rule:

- **transport security** — the graph records endpoints, not whether they are TLS.
  Read `context/integration-surface.md` and say which are plain HTTP;
- **authorisation** — no rule models who may invoke an exposed process. An endpoint
  with no policy looks identical to one with a policy the parser cannot see;
- **error handlers that swallow** — `CORR-001` fires only when a process has *no*
  handler. A catch that logs and continues is worse in an integration than no catch,
  because the message is lost silently;
- **credentials outside shared resources** — a secret in a module property default or
  a mapping literal is not a `SharedResource` and does not trigger `SEC-001`;
- **what the module reaches that this tree does not contain** — every
  `ExternalReference` (`DEBT-003`) is an unreviewed dependency.

## 5. Caveats

Say plainly that this review covers what is **statically visible in the scanned
modules**. It does not cover:

- runtime configuration — deployment properties, engine settings and the platform
  credential store are outside the source tree entirely, so a credential that looks
  hardcoded here may be overridden at deployment, and one that looks safe may not be;
- activities that build SQL at runtime, which carry no `sqlStatement` and so trigger
  no `PERF-001` — their absence from a finding is not evidence they are well-formed;
- anything in a module outside the analysed tree.

Quote the coverage figures with the conclusion — see
[analysis-trust](../skills/analysis-trust/SKILL.md). A clean security result over a
tree with unresolved references is a statement about the scan, not about the estate.

## 6. Cross-estate

A TIBCO security answer is usually incomplete on its own, because what the estate
reaches is in another graph. If the Oracle and APEX analyses exist, run:

```bash
PYTHONPATH=tools python -m estate_analyzer -o analysis_output_estate findings \
  --estate cross --min-severity HIGH
```

`XE-003` (transaction boundary) and `XE-007` (a user surface over an integrated
table) are correctness findings with security consequences: both describe state
crossing a boundary that neither side fully controls. Namespace source-estate rule
ids as `TIB.SEC-001` when the answer spans estates — the same ordinal means something
different in each catalogue.
