---
name: migration-planner
description: Plan and scope a modernisation of a TIBCO, APEX or Oracle estate from the analyzers' graphs — use when asked what to migrate first, how to break a monolith into migratable units, how big a rewrite is, which components are safe to move independently, what has to be decided before anything moves, how to prove a migrated component still behaves the same, or to build a wave plan or migration backlog.
---

# Planning a modernisation from the graph

Sequencing is a solved, derived question — do not invent an order. This skill is
about the questions *around* the order: what the unit of migration is, how big each
one is, what proves it still works, and what should not be migrated at all.

**Everything here is a number an analyzer already computed.** If you find yourself
estimating, stop and check whether the graph already knows.

## The order is derived, not argued

One rule produces it: *a component may not be cut over before the data it shares has
an owner.*

```bash
PYTHONPATH=tools python -m estate_analyzer -o analysis_output_estate sequence \
  --save analysis_output_estate/reports/cutover-sequence.md
```

| Wave | Meaning | What to do with it |
|---|---|---|
| 0 — Decide | contended tables, unmapped datasources, unresolved references | Not work items. Open questions every later wave depends on. Nothing moves until these are answered. |
| 1 — Together | components writing the same table from different estates | One unit or not at all. Splitting the writer set across two runtimes is the classic failed cutover. |
| 2 — Follow | touch shared data, contend with nobody | Follow whoever owns that data. |
| 3 — Free | touch no shared data | **Start here.** Wave 3 is not unimportant, it is *unblocked*. |

For the full walkthrough use the `estate-cutover-sequence` prompt. Do not restate its
output as your own reasoning.

## What a migration unit actually is

A wave gives you components. A stakeholder does not recognise `CUSTOMER_PKG.CREATE_CUSTOMER`
— they recognise "customer onboarding". The business layer bridges that:

```cypher
MATCH (d:BusinessDomain)<-[:PART_OF_DOMAIN]-(f:BusinessFunction)
      -[:IMPLEMENTED_BY]->(u:DbProgramUnit)
MATCH (u)-[:EXECUTES_SQL]->(:SqlStatement)-[:WRITES_TO]->(t:DbTable)
RETURN d.name AS Domain, f.name AS Function, f.origin AS Origin,
       f.confidence AS Confidence, collect(DISTINCT t.name) AS Writes
```

**Check `origin` before putting a name in a plan.** A `derived` function is the
analyzer's guess from package grouping and writes, at confidence 0.4–0.5. A
`declared` one came from `--business-map` and is a stated fact. Presenting the first
as the second is the fastest way to lose a room. If the business names matter to this
plan, the fix is to supply the map — not to argue for the derived names.

## Sizing each unit

| Question | Where it already is |
|---|---|
| How complex? | `complexity` and `tier` on program units; `context/complexity.md` |
| How much depends on it? | `fanIn` / `fanOut`, or the `hotspots` query |
| What breaks if it moves? | `impact --target … --direction upstream` |
| What does it touch? | `context/data-access.md`, the `access-verbs` query |
| What is externally callable? | `context/entry-points.md` |

A unit with high `fanIn` is not "hard" — it is *expensive to get wrong*. Sequence
around it; do not necessarily start with it.

## What proves it still works

This is the question most migration plans answer last and should answer first. Where
utPLSQL annotations exist, the graph knows:

```cypher
MATCH (u:DbProgramUnit)-[:HAS_TEST]->(c:TestCase)
RETURN u.packageName AS Package, u.name AS Unit,
       c.suite AS Suite, collect(c.displayName) AS Cases
```

And the inverse — the migration risk register:

```cypher
MATCH (u:DbProgramUnit)
WHERE (u.isPublished OR u.isStandalone) AND NOT u.declaredOnly
  AND NOT (u)-[:HAS_TEST]->(:TestCase)
  AND (u)-[:EXECUTES_SQL]->(:SqlStatement)-[:WRITES_TO]->()
RETURN u.packageName AS Package, u.name AS Unit, u.complexity AS Complexity
ORDER BY Complexity DESC
```

Callable from outside, changes data, nothing covers it. **Write the characterisation
test before the rewrite, not after** — and say plainly that untested high-complexity
units are where a migration budget actually goes.

One caveat that matters: **no `TestCase` nodes means "this repository carries no
utPLSQL tests", not "this code is untested."** The tests may live somewhere the
analyzer never saw. Never report zero coverage without saying which of the two it is.

## What not to migrate

Dead code is the cheapest win in any modernisation, and the easiest thing to get
wrong. `context/dead-code.md` exists for all three estates.

Before recommending any deletion, check all four:

1. Dynamic / runtime SQL — Oracle `SEC-001`, estate `XE-006`
2. `context/unresolved.md`
3. Unmapped datasources — estate `XE-005`
4. Callers outside the scanned tree — external jobs, ORDS, schedulers, other modules

TIBCO draws this distinction explicitly and it generalises: `CORR-002` is a process
with **no starter at all** — it cannot run. `DEBT-001` has a starter, so it *does*
run; it is simply not part of any flow this tree shows. Recommending deletion for the
second without checking outside the tree is how a live interface gets decommissioned.

## What must be fixed on the way

Some findings are migration blockers rather than backlog items, because they change
the plan rather than the code:

| Finding | Why it blocks |
|---|---|
| `XE-001` contended table | Decides ownership, and therefore wave 1 membership. Surface it before the plan hardens. |
| `XE-003` transaction boundary | The integration cannot see the database's boundary. A retry can act on half-finished work — a timing bug that survives testing. |
| `XE-007` page over integrated table | The page shows state no APEX code produced. A defect there looks like an APEX defect and is not one. |
| Oracle `SEC-001` dynamic SQL | The unit's real reads and writes are unknown. Every completeness claim about it is provisional. |
| Oracle `DEBT-001` spec with no body | Either the body is deployed but uncommitted, or the package is unimplemented. Both change scope. |

## Writing the plan

Lead with wave 0. A plan that opens with "start with X" when three ownership
questions are unanswered is a plan that will be re-cut.

For each unit give: the business name (with its `origin`), the wave and why, size
(`complexity`, `fanIn`), what proves it (`TestCase` count, or its absence), and the
blockers. Then state coverage — see
[analysis-trust](../analysis-trust/SKILL.md). A migration plan built on a graph with
60% bind coverage is a plan with unknown scope, and that has to be visible on the
first page, not the last.

Style: British-neutral professional English, no emoji, no hype, tables over prose
when carrying more than three facts, uncertainty stated plainly with the command that
would remove it.
