---
mode: agent
description: Derive and explain the order in which a mixed TIBCO, APEX and Oracle estate should be modernised.
---

# Cross-estate cutover sequence

Produce the migration order, and defend it from the graph. The rule the sequence
follows is one line: **a component may not be cut over before the data it shares has
an owner.** Everything else falls out of that.

## 1. Derive it

```bash
PYTHONPATH=tools python -m estate_analyzer -o analysis_output_estate sequence \
  --save analysis_output_estate/reports/cutover-sequence.md
```

The waves are:

| Wave | Meaning |
|---|---|
| 0 — Decide | open questions every later wave depends on the answer to |
| 1 — Together | components writing the same table from different estates; they cut over as one unit or not at all |
| 2 — Follow | components touching shared data but contending with nobody; they follow whoever owns that data |
| 3 — Free | no shared data, therefore no cross-estate ordering constraint |

## 2. Interrogate wave 0 before anything else

Wave 0 is not a to-do list; it is a list of things that are currently unknown, and
each one weakens every wave after it.

| Kind | What it means | What resolves it |
|---|---|---|
| `ownership` | a table more than one estate writes | a decision by the owning teams, recorded |
| `unmapped-datasource` | a JDBC resource with no estate-map entry | one entry in `estate_map.json` |
| `unmodelled-dependency` | TIBCO names a table no database estate defines | extend the Oracle analysis to that schema, or fix the map |
| `runtime-sql` | an activity that builds SQL at runtime | read the activity by hand and record what it touches |

For each, say who must decide, and what happens to the sequence if they decide the
other way. A plan that does not say that is a guess with a Gantt chart.

## 3. Sanity-check the waves against the findings

Cross-reference the sequence with `findings --category CROSS_ESTATE`:

- every `XE-001` contended table should appear as a wave 1 group
- every `XE-003` transaction-boundary conflict should be called out inside its group —
  those two writers cannot simply be sequenced, they need a boundary decision first
- every `XE-007` page should appear in the regression scope for its group's cutover
- `XE-004` duplicates are a wave 2 or 3 decision: one estate keeps the logic, the
  other calls it

If a contended table has no group, or a group has no table, the sequence and the
findings disagree and one of them is wrong. Say so rather than picking.

## 4. Write it up

For each wave, in order:

- What moves, by estate, with the artefact names from the report
- Why it can move then and not earlier — cite the shared object that constrains it
- What must be true before it starts
- What must be re-tested when it lands, and by whom
- The confidence of the crossings that put it in this wave; anything resting on a
  `name`-basis edge (0.5) is a placement to confirm before planning

Start the write-up with wave 3, not wave 0. Wave 3 is what is unblocked today, and it
is the most useful thing a reader can act on this week; wave 0 is what someone must
decide before the rest becomes plannable.

## 5. State what the sequence does not account for

The order is derived from data coupling alone. It knows nothing about:

- service and message coupling — a TIBCO process calling an APEX REST endpoint, or two
  processes coupled through a queue, does not constrain this sequence even though it
  constrains the real cutover
- file hand-offs between estates
- effort, team capacity, licence expiry, contractual dates or infrastructure lead time
- business criticality and change freezes
- anything behind an unmapped datasource or a runtime-SQL activity — those components
  may belong in an earlier wave than the one they are shown in

Quote `sqlBindCoverage` and `datasourceCoverage` next to the sequence. Below 80 %,
present it as a first draft that will move once the estate map is complete, not as a
plan.
