# Rule catalogue

Deterministic rules run by `apex-analyze rules`. Each produces an `:Issue` node with
`origin: derived` and `confidence: 1.0`, linked to the component that triggered it and
to a `:Recommendation`. An agent explains and prioritises these; it does not re-detect them.

| Rule | Category | Severity | Triggers when | Recommended action | Effort |
|---|---|---|---|---|---|
| `SEC-001` | SECURITY | CRITICAL | SQL injection through dynamic SQL | Replace concatenation with bind variables, or validate through DBMS_ASSERT before assembling the statement. | M |
| `SEC-002` | SECURITY | HIGH | Unsecured page performs DML | Attach an authorization scheme to the page, or to each process that writes. | S |
| `SEC-003` | SECURITY | HIGH | Unrestricted page access with unprotected items | Set page access protection to "Arguments Must Have Checksum" and give key items session state protection. | S |
| `SEC-004` | SECURITY | HIGH | Public page queries application data | Confirm the page is intended to be public and that its query is scoped to data safe for anonymous users. | M |
| `SEC-005` | SECURITY | MEDIUM | Primary key item is tamperable | Set session state protection to "Checksum Required" on key items. | S |
| `SEC-006` | SECURITY | MEDIUM | Unused authorization scheme | Apply the scheme or delete it; an unused scheme suggests a control that was intended but never wired up. | S |
| `SEC-007` | SECURITY | MEDIUM | Substitution string in SQL | Use `:ITEM` bind syntax so the value is bound, not inlined. | S |
| `SEC-008` | SECURITY | LOW | Credential-shaped session state | Hold secrets in a credential store, not in session state. | M |
| `PERF-001` | PERFORMANCE | HIGH | SELECT * in a region source | Name the columns the region actually renders. | S |
| `PERF-002` | PERFORMANCE | HIGH | Per-row LOV query in a report | Join the lookup into the report query, or switch the column to a shared static LOV. | M |
| `PERF-003` | PERFORMANCE | HIGH | Report over a large table | Confirm pagination is bounded and the driving predicate is indexed. | M |
| `PERF-004` | PERFORMANCE | MEDIUM | Wide join with no bound predicate | Add a bind-variable predicate, or move the query behind a view with a driving filter. | M |
| `PERF-005` | PERFORMANCE | MEDIUM | Hardcoded optimizer hint | Remove the hint and fix the underlying statistics or index. | M |
| `PERF-006` | PERFORMANCE | MEDIUM | Duplicated SQL statement | Extract the query into a database view or a shared component. | M |
| `PERF-008` | PERFORMANCE | MEDIUM | Database link used during rendering | Cache or materialise the remote data; a remote call on the render path makes page latency depend on another database. | L |
| `CORR-003` | CORRECTNESS | HIGH | Exception silently swallowed | Log the error and re-raise, or handle the specific exception. | S |
| `CORR-004` | CORRECTNESS | MEDIUM | COMMIT inside a page process | Let APEX manage the transaction; remove the explicit COMMIT. | S |
| `CORR-006` | CORRECTNESS | MEDIUM | Submit button reaches nothing | Condition a process on the button, or change it to a redirect. | S |
| `DEBT-001` | TECH_DEBT | MEDIUM | Unreachable page | Delete the page, or add the navigation that was intended. | S |
| `DEBT-002` | TECH_DEBT | LOW | Unused shared component | Delete it, or wire it up. | S |
| `DEBT-003` | TECH_DEBT | LOW | Component disabled by a build option | Remove the component and the build option once the feature decision is final. | S |
| `DEBT-004` | TECH_DEBT | MEDIUM | Deprecated component or API in use | Migrate to the supported equivalent before the next APEX upgrade. | M |
| `DEBT-005` | MAINTAINABILITY | LOW | Large inline JavaScript block | Move the code into a static application file so it can be cached, linted and reviewed. | S |
| `DEBT-006` | MAINTAINABILITY | MEDIUM | Duplicated PL/SQL block | Extract the logic into a package procedure and call it from each component. | M |

## Raised during parsing

These come from the binder rather than a graph query, because only the parser knows
the reference could not be resolved.

| Rule | Category | Severity | Meaning |
|---|---|---|---|
| `CORR-001` | CORRECTNESS | HIGH | Reference to a missing database object |
| `CORR-002` | CORRECTNESS | HIGH | Item sourced from a missing column |
| `CORR-005` | CORRECTNESS | MEDIUM | Branch targets a page that does not exist |

## Using them

```bash
apex-analyze rules --category SECURITY --min-severity HIGH
apex-analyze rules --rule SEC-002 --json
apex-analyze rules --fail-on CRITICAL      # exit 2 in CI
```

Severity is fixed by the rule, not by the finding. Judgement about *this* application
belongs in your narrative, not in a rewritten severity.
