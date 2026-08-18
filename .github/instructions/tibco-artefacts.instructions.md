---
name: TIBCO artefacts — analyse, do not read
description: Applies when a TIBCO BusinessWorks source file is in context. Route the question through the analyzer instead of reading the XML.
applyTo: "**/*.process,**/*.bwp,**/*.xsd,**/*.wsdl,**/*.xsl,**/*.xslt,**/*.substvar,**/*.aeschema,**/*.bwm,**/*.shared*,**/*.httpProxy,**/*.rvtransport"
---

# You are looking at a TIBCO source artefact

This file is **input to the analyzer, not a source of answers.** Everything structural about it
has already been parsed into `analysis_output/graph.json`. Reading the XML to count activities,
guess callers, infer an entry point or estimate complexity is a defect, not diligence — the
graph resolves cross-file references that no single file shows.

## Run this instead

```bash
# once per source tree, or whenever the TIBCO source changes
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output analyze --source <tibco_root>
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output validate
```

Then route by question:

| Question about this file | Command |
|---|---|
| What is in it — activities, transitions, error handlers, schema elements | `context` → read `analysis_output/context/processes/<Name>.md` |
| Who calls or depends on it | `impact --target "<Label>:<Name>" --direction upstream` |
| What it depends on | `impact --target "<Label>:<Name>" --direction downstream` |
| Is it dead / unreferenced | `analysis_output/context/dead-code.md` |
| Is it an entry point | `analysis_output/context/entry-points.md` |
| Where a piece of functionality lives | `search "<question>"` (needs `index --no-embeddings` once) |
| Its schema consumers and namespaces | `analysis_output/context/data-contracts.md` |

`--target` accepts a node id (`bwp_0002`), an exact name, a `Label:Name` pair, or this file's
path — so you can pass the open file directly:

```bash
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output \
  impact --target "<this file's path>" --direction upstream --depth 4
```

On `Ambiguous target` — a schema path matches both the `XSD` and an `Element` of the same name —
narrow it with `--label XSD`, pass the node id, or use `--all-matches`. On "no artefact matches",
the file is outside the analysed source tree: re-run `analyze` with the right `--source`.

## Reading this file *is* right for

- Confirming something a command already surfaced, before you cite it.
- Quoting a literal the graph does not model — an XPath expression, a mapping body, a
  condition string, a comment.
- Investigating a suspected parser gap, where the fix belongs in `tools/tibco_analyzer/parsers/`.

In each case, say which command surfaced the artefact first, then quote the file.

## Never

- Edit a `.process`, `.bwp`, `.xsd`, `.wsdl` or shared-resource file to "fix" an analysis result.
  These are the legacy estate under study; the fix belongs in the parser or in the narrative.
- Report a count, dependency or blast radius derived by eye from this XML.
- Guess at an unresolved reference. If the target is not in the scanned tree, it is an
  **ExternalReference** — say "unresolved reference — target not present in the scanned tree".

Full rules: [copilot-instructions.md](../copilot-instructions.md).
