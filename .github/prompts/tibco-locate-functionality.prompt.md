---
mode: agent
description: Answer "where is X implemented?" by running semantic search over the knowledge graph, confirming each hit in its source file, and mapping the functionality across processes, activities and schemas.
tools: ['codebase', 'terminal']
---

# Locate functionality in the TIBCO estate

Turn a business question into an evidenced answer about which processes, activities and schemas
implement it.

**Question:** `${input:question:Where is the credit score calculated?}`

## Preconditions

The search index must exist:

```bash
ls -1 ${input:outputDir:analysis_output}/search_index/ 2>/dev/null \
  || PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} index --no-embeddings
```

If `graph.json` is missing, run `tibco-bootstrap-analysis` first. Never answer this question by
grepping the TIBCO XML.

## Procedure

1. **First pass — ask the question as asked.**

   ```bash
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} \
     search "${input:question:Where is the credit score calculated?}" --top 10
   ```

   The output gives, per hit: rank, label and name, file path, module, node id, a "Why" summary,
   matched terms, and graph context (defined in, entry point, uses schemas, calls, used by,
   Spring targets). The header states the mode — `lexical` or hybrid — and the embedding
   provider. If it says `lexical`, matching is BM25 over terms; phrase the query with words that
   actually occur in artefact names.

2. **Judge result quality.** Results are weak when:

   - no hit shares a matched term that matters to the question;
   - every hit is the same label and none is a `BWProcess` or `Activity`;
   - the top hits are schemas when the question is about behaviour (or vice versa);
   - `totalCandidates` is small and the hits look arbitrary.

3. **Reformulate and filter when results are weak.** Try, in order:

   - **TIBCO vocabulary instead of business vocabulary** — activity type names
     (`JDBC`, `SOAP`, `JMS`, `Mapper`, `Timer`), schema element names, endpoint fragments.
   - **Narrow by label:**

     ```bash
     PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} \
       search "score calculation" --label BWProcess --label Activity --top 10
     ```

   - **Narrow by module** (repeatable, and combinable with `--label`):

     ```bash
     PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} \
       search "score" --module CreditApp.module --top 10
     ```

   - **Split a compound question** into separate searches — one per noun — and intersect the
     results yourself.
   - **Follow the graph context** from a promising hit: its `Calls`, `Used by` and
     `Uses schemas` lines name the next things to search for.

   Record every query you ran. The path to the answer is part of the answer.

4. **Confirm every hit you intend to cite by opening the cited file.** This is the one place
   where reading source is required.

   ```bash
   sed -n '1,80p' <filePath from the search output>
   ```

   Confirm the artefact is really what the "Why" summary claims: the activity type, the target
   it calls, the schema it maps. If the file does not support the claim, drop the hit and say so.
   `Activity` hits often have no file of their own — open the owning process named in
   "Defined in" instead.

5. **Establish the shape of the implementation.** For the confirmed hits, pull the surrounding
   facts rather than inferring them:

   ```bash
   cat ${input:outputDir:analysis_output}/context/processes/<ProcessName>.md
   ```

   and, if the functionality is reached from outside, check whether the process is an entry
   point in `context/entry-points.md`.

6. **Optional — one step further.** If the questioner is heading towards a change, offer the
   blast radius:

   ```bash
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} \
     impact --target "BWProcess:<Name>" --depth 3
   ```

   Do not run a full impact analysis unless asked; point at the `tibco-impact-analysis` prompt.

## Report format

```
## Answer

<Two or three sentences: where the functionality lives, and how it is reached.>

## Where it is implemented

| Artefact | Type | Module | File | Node | Role in the answer |
|---|---|---|---|---|---|

## How it is reached

<Entry point → process → activity chain, taken from the graph context and the process pack.>

## Data contracts involved

| Schema | Namespace | Used by | File |
|---|---|---|---|

## Search trail

| # | Query | Filters | Useful hits |
|---|---|---|---|

## Confidence and gaps

<What was confirmed by opening a file; what the graph does not capture — mapping expression
detail, runtime configuration, external system behaviour.>
```

## Acceptance criteria

- Every artefact in the answer carries a file path and a node id from search output.
- Every cited hit was confirmed by opening its file (or its owning process).
- The search trail lists every query run, including the ones that failed.
- Where the search found nothing, the answer says "not found in the scanned tree" and names the
  queries tried — it does not guess a likely location.

## Do not

- Do not grep the TIBCO tree instead of running `search`.
- Do not name a process, activity or schema that did not appear in search output.
- Do not claim semantic/vector matching when the header says `lexical`.
- Do not describe what an activity does beyond its parsed type and target.
- Do not infer that similar names mean related functionality without a graph edge to back it.
