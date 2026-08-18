# Semantic search reference

`search` answers "where is X implemented?" over the parsed estate. It is a retrieval
aid, not an oracle: it produces a ranked shortlist with graph context attached, and
you verify the winner against the process context pack before asserting anything.

```bash
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output index --no-embeddings
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output search "<question>" --top 10
```

## How the index is built

`index` reads `graph.json` (and, when the source root is known, the original XML) and
writes `<output>/search_index/` containing `search_index.json` (documents + BM25
statistics), `search_vectors.json` and, when embeddings are used,
`embedding_cache.json`.

### One document per artefact

Indexed labels: `BWProcess`, `Activity`, `XSD`, `Element`, `ComplexType`, `Service`,
`Operation`, `SharedResource`, `GlobalVariable`, `DataTransformation`, `AESchema`,
`System`, `ErrorHandler`, `Module`.

Document text deliberately mixes structure with behaviour, because business questions
are usually answered by the latter:

| Document | What goes into its text |
|----------|-------------------------|
| `BWProcess` | Name, module, entry type, endpoint, target namespace, tier, every activity name, every activity category and Spring target, the schemas it uses, the XPath transition conditions, and a flattened blob of the raw `.process` XML |
| `XSD` | Name, namespace, folder, every element name with its XSD and Java type, and the names of the artefacts that consume it |
| `Service` | Name, namespace, binding style, endpoint URL, operation names, and a flattened blob of the WSDL |
| Everything else | Name, module, owning artefact, and all scalar properties |

Each document also carries a generated one-line `snippet` — the "Why" line in the
output — and is capped at 6,000 characters.

The raw-XML blob is only included when the source tree is reachable. If `index` was
run without the source (or the tree has moved), documents fall back to graph
properties alone; recall on XPath conditions, SQL fragments and log messages drops.
Re-run `index --source <tibco_root>` to restore it.

### Identifier-aware tokenisation

`CreditScoreLookup_v2` becomes `credit`, `score`, `lookup`, `v2`. Splitting is on
non-alphanumerics and on camel-case boundaries, then lowercased. There is no
stemming and no model, so tokenisation is deterministic: the same input always yields
the same index.

Stopwords remove both English filler (`the`, `where`, `how`, `find`, `show`) and
domain noise that would otherwise match everything (`tibco`, `com`, `plugin`, `core`,
`pe`, `xml`, `xmlns`, `ns`, `tns`, `implemented`, `implementation`). Single-character
tokens are dropped.

### BM25 with field boosts and label priors

Okapi BM25 with `k1 = 1.5` and `b = 0.4` — mild length normalisation, because a large
process document is legitimately large rather than padded.

| Field | Term frequency multiplier |
|-------|---------------------------|
| Artefact name | 3.0 |
| Snippet | 1.5 |
| Body text | 1.0 |

After scoring, each document is multiplied by a prior on its label. "Where is X
implemented?" is answered by a process or a service far more often than by a single
schema element, and the ranking reflects that before any query is seen:

| Label | Prior | Label | Prior |
|-------|-------|-------|-------|
| BWProcess | 1.8 | GlobalVariable | 1.0 |
| Service | 1.5 | Operation | 1.0 |
| Activity | 1.3 | Module | 0.9 |
| DataTransformation | 1.2 | ErrorHandler | 0.8 |
| XSD | 1.1 | ComplexType | 0.7 |
| SharedResource | 1.1 | Element | 0.6 |

Practical consequence: an `Element` hit that outranks a `BWProcess` hit had
substantially stronger term evidence. Treat it as a signal that the concept is a data
field rather than a behaviour.

### Domain synonym expansion

Query tokens are expanded with integration-domain synonyms at 0.45 weight, so
`queue` also matches `jms`, `destination`, `mq`, `topic`; `db` matches `jdbc`,
`database`, `sql`, `datasource`, `table`; `error` matches `fault`, `exception`,
`catch`, `failure`, `rethrow`; `transform` matches `map`, `mapper`, `mapping`,
`xslt`. Only original (weight 1.0) tokens are reported as **matched terms**, which is
what makes that field diagnostic: if a hit shows no matched terms, it was reached
purely by synonym expansion and deserves less confidence.

### Optional embeddings

Vector search is strictly optional and strictly degradable. Providers are tried in
order: `sentence-transformers` (local, offline, no key), an OpenAI-compatible
endpoint (`OPENAI_API_KEY`, optional `OPENAI_BASE_URL`), then Azure OpenAI
(`AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT`). Force one with
`--provider sentence-transformers|openai|azure-openai`; suppress entirely with
`--no-embeddings`.

If no provider is available, or embedding fails mid-build, the engine logs the reason
and continues lexical-only. Vectors are cached by a hash of the document payload, so
re-indexing after a partial change only re-embeds what changed.

**Always state the mode.** The search output header reads `Mode: lexical` or
`Mode: hybrid` with the provider name. A lexical-only result is valid; presenting it
as semantic is not.

### Fusion

Lexical and vector result lists are combined with reciprocal-rank fusion,
`score = Σ 1 / (60 + rank)` across the lists a document appears in. The resulting
score is a fusion score, not a similarity or a probability. It is comparable within
one query's result set and meaningless across queries — never quote it as a
confidence.

Label and module filters are applied after fusion, so filtering narrows the same
candidate pool rather than re-ranking a different one.

## Phrasing queries for a TIBCO estate

| Do | Do not |
|----|--------|
| Use domain nouns the estate would name things after: `credit scoring`, `customer enrichment`, `settlement file` | Ask conversationally: `can you tell me about the code` |
| Name the technology when the question is technical: `jms queue send`, `jdbc stored procedure`, `soap fault handler` | Use Spring vocabulary the estate never contained: `@RestController`, `bean`, `repository` |
| Use the artefact vocabulary: `retry`, `archive`, `poller`, `validate`, `enrich` | Include `TIBCO`, `process`, `implementation` — all stopwords |
| Try two or three phrasings and compare | Assume the first ranking is authoritative |

Filters:

| Flag | Effect |
|------|--------|
| `--label BWProcess` | Restrict to a label; repeatable. Use `--label BWProcess --label Service` for "which component" questions |
| `--module CreditApp.module` | Restrict to a module; repeatable. Use when the estate is large and the question is scoped |
| `--top N` | Result count; default 10. Use 3–5 when you intend to verify each hit |
| `--json` | Machine-readable, including `graphContext` for every hit |
| `--save <path>` | Also write the Markdown result, for citing in a report |

Recommended pattern: start unfiltered and broad, read the label mix in the results
(that tells you whether the concept is behaviour, data or configuration), then re-run
with `--label` to get a clean shortlist.

## Interpreting a hit

Every hit carries the graph neighbourhood that makes it actionable:

| Field | Read it as |
|-------|-----------|
| **File** | The citation. `n/a` means a node without its own file (`Activity`, `Element`, `Operation`, `ErrorHandler`) — cite the owner instead |
| **Node** | The stable id to quote and to pass to `impact` |
| **Why** | The generated snippet: entry type, activity count, tier, or category → Spring target |
| **Matched terms** | Original query tokens that hit. Empty or generic means a weak hit |
| **Defined in** | The owning process or schema for a child node |
| **Entry point** | Present when the process is externally reachable — a strong signal it is the answer to "where does this start?" |
| **Uses schemas / Calls / Used by** | Immediate dependencies and dependants |
| **Spring targets** | The distinct Spring constructs its activities map to — useful sizing colour |

A hit is strong when the matched terms are specific, the label matches the kind of
thing the question asks about, and the graph context is consistent with the claim
(for example, a process claimed to "send to a queue" should show a JMS activity or a
JMS shared resource).

## Worked example

**Business question:** "Where is credit scoring calculated, and who would notice if
we changed it?"

**Query**

```bash
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output \
  search "where is credit scoring calculated" --top 3
```

**Hits (abridged, from the bundled sample project)**

```
Mode: lexical (embeddings: none) | candidates: 15 | shown: 3

## 1. BWProcess: ScoreCalculationProcess
- File: CreditApp.module/Processes/ScoreCalculationProcess.process
- Module: CreditApp.module | Node: bwp_0004
- Why: NONE process, 3 activities, tier Medium (10.5)
- Matched terms: credit, scoring
- Uses schemas: CreditResponse
- Used by: CallScoreCalculation, InvokeCreditCheck
- Spring targets: JmsTemplate.send(), MapStruct / ModelMapper, Native Java class

## 2. Activity: ApplyScoringRules
- Module: CreditApp.module | Node: act_0016
- Why: JAVA_ACTIVITY -> Native Java class (in ScoreCalculationProcess)
- Matched terms: credit, scoring

## 3. BWProcess: MainCreditProcess
- File: CreditApp.module/Processes/MainCreditProcess.process
- Node: bwp_0002 | Entry point: HTTP_RECEIVER
- Matched terms: credit, scoring
```

**Reading it.** Hit 1 is a process with both query terms matched and no entry type,
so it is internal logic — consistent with "calculated". Hit 2 is an activity *inside*
hit 1, which corroborates rather than competes. Hit 3 is the HTTP entry point that
reaches it. The shape of the result set is itself the answer: an internal calculation
called from a public endpoint.

**Verification.** Open `analysis_output/context/processes/ScoreCalculationProcess.md`
and confirm the activity sequence actually performs scoring (here: a mapper, the
`ApplyScoringRules` Java activity, then a JMS send). Never skip this step — a name
match is not an implementation.

**Consequence.** The follow-up half of the question is an impact run, not a search:

```bash
PYTHONPATH=tools python -m tibco_analyzer -o analysis_output \
  impact --target "BWProcess:ScoreCalculationProcess" --direction upstream --depth 4
```

**Answer, written up.** Credit scoring is implemented in `ScoreCalculationProcess`
(`bwp_0004`, `CreditApp.module/Processes/ScoreCalculationProcess.process`), a
Medium-tier internal process of 3 activities whose scoring step is the
`ApplyScoringRules` Java activity (`act_0016`) — a `Native Java class` in the Spring
target, so the rules are not visible in the BW XML and need separate review. It is
invoked from `MainCreditProcess` (`bwp_0002`, `HTTP_RECEIVER`) via the
`CallScoreCalculation` activity, so any behavioural change surfaces on the HTTP
endpoint. Evidence: `search "where is credit scoring calculated"`,
`context/processes/ScoreCalculationProcess.md`.

## Failure modes

| Symptom | Cause | Response |
|---------|-------|----------|
| `Search index not found` | `index` not run for this output dir | Run `index`, add `--no-embeddings` if offline |
| `candidates: 0` | No query token survived tokenisation, or none exists in the corpus | Rephrase with a distinctive noun; if still zero, report that no artefact matches |
| All hits from one module, question was estate-wide | Vocabulary is module-specific | Re-run with `--label BWProcess` to widen beyond activity-level noise |
| High-ranking hit with no matched terms | Reached by synonym expansion only | Downgrade it; verify or discard |
| `Mode: lexical` when semantics were expected | No embedding provider available | Say so. Install `sentence-transformers` or set a key, then re-run `index` |
| Results look stale after a source change | Index built from an older graph | Re-run `analyze` then `index`; the index does not auto-refresh |
