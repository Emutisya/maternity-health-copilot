# Maternity Health Copilot | AI for Health

### Make every care conversation easier to prepare for.

**Maternity Health Copilot is a local-first educational navigation and
appointment preparation system for pregnancy and postpartum.** It turns bounded
stage, topic and format preferences into ranked educational conversation
starters and a printable question list for discussion with a qualified
healthcare professional.

[![CI](https://github.com/Emutisya/maternity-health-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/Emutisya/maternity-health-copilot/actions/workflows/ci.yml)

> Not medical advice. For symptoms or concerns, contact a qualified healthcare professional. If you think there is an emergency, contact local emergency services.

## The invention thesis

A care appointment is not only a clinical encounter. It is also a conversation:
what to ask, what to clarify, and how to prepare. Information is useful only
when someone can navigate it and carry the right questions into that conversation.

This project explores a deliberately bounded role for AI: **organize educational
topics and support preparation, while leaving clinical judgment with qualified
professionals.** It does not need a person's symptom narrative or medical record
to demonstrate that workflow.

The global ambition is an accessible preparation layer around human maternity
care: locally usable educational navigation, professionally reviewed content,
and multilingual question planning. Reaching that ambition requires clinical,
community and accessibility review; the current release establishes the
working retrieval and preparation core.

## Experience the working system

| Step | What the Copilot does today |
| --- | --- |
| Orient | Lets the user choose pregnancy or postpartum as a bounded preference |
| Focus | Offers six educational topics, two formats and planning/support preferences |
| Discover | Uses a fitted TF-IDF model to rank stage-compatible demo resources |
| Prepare | Lets the user select fixed questions for a healthcare conversation |
| Carry | Provides a print view with the educational-use notice |
| Reset | Clears selections without retaining a health profile |

The dashboard is connected to actual Python inference. The model ranks
educational catalog entries; it never predicts a health outcome.

### Design choices that matter

- **Preparation, not diagnosis.** No symptom collection, triage or treatment generation.
- **Bounded content.** Outputs come from a fixed catalog, not generated medical advice.
- **Local-first execution.** No external model service, patient database or API key.
- **Human care stays central.** Questions support a professional conversation, not replace it.

**Current release:** a working local research prototype with synthetic personas
and demonstration content. It has not undergone clinical review or patient
evaluation and does not provide individualized care or determine whether anyone
is safe.

## Run locally

Clone the standalone project:

```powershell
git clone https://github.com/Emutisya/maternity-health-copilot.git
Set-Location maternity-health-copilot
```

Python 3.10+ is the only runtime requirement. No installs, API keys, network calls, downloaded weights or CDNs are needed. From this directory in PowerShell:

```powershell
python -m maternity_copilot train
python -m maternity_copilot evaluate --split held_out --k 3
python -m maternity_copilot match --stage pregnancy --topic appointments --format guide --focus planning
python -m maternity_copilot serve
```

Open **http://127.0.0.1:8765**. Stop with Ctrl+C. Use `serve --port 8766` if that port is occupied, and open the corresponding loopback URL. Models are regenerated locally and ignored by Git. Global `--model` belongs **before** the subcommand:
All artifact writers require `.json` destinations outside the packaged
`maternity_copilot\` source/data tree, after resolving symlinks. Training cannot
accidentally replace the catalog or source, and JSON exports cannot overwrite
README, Python or packaging files. Global `--model` belongs **before** the subcommand:

```powershell
python -m maternity_copilot --model models\demo.json train
python -m maternity_copilot --model models\demo.json serve
python -m unittest discover -s tests -v
```

The packaged, single-file HTML has all its styles and scripts inline. Opening it directly shows the interface but cannot perform inference: serve it through Python. Synthetic presets, bounded topic/preferences, resource cards, selected appointment questions and an optional print view are available. Changing selections clears old matches. Refresh/reset clears the question list; no browser storage is used.
While searching, the Cancel search button or Escape aborts the request,
restores focus to Find resources and prevents late responses from repopulating
the page. Cancellation draws no clinical conclusion.
Before transport, the dashboard verifies selections against the bounded enums,
marks/focuses invalid controls and links them to a nonreflective recovery
message. Correcting selections clears the error state. Server validation
remains authoritative; this is not symptom screening. The optional browser
scenario `validation` verifies zero requests for an unsupported DOM value.
The dashboard distinguishes unavailable catalog/model (restore/train/restart),
invalid selections (reset/reselect) and unreachable backend failures. An
explicit Retry button repeats only the current bounded synthetic selections;
it never retries automatically. Browser scenario `recovery` exercises a 503
then a successful real-backend retry without stale cards.
A keyboard-visible skip link and section navigation move focus to demo,
resource and planner headings. Keyboard-initiated searches focus the results
heading on completion only if focus has not moved to another control; sticky
notice spacing keeps headings visible. Browser scenario `navigation` uses
real Enter key events to verify these focus destinations.
Each selected question can be removed directly from the planner, synchronizing
all matching card checkboxes and moving focus to the next retained control.
Clear question list only preserves the current matches/preferences, unlike
Reset demo. A live count announces list changes. Browser scenario `planner`
verifies removal, focus, checkbox synchronization and clearing without search.
Move up/down buttons reorder fixed planner questions, preserving selected
checkboxes and focus on the moved item; unavailable boundary moves are
disabled. This is the demonstrator's conversation order, not a clinical
priority. Browser scenario `ordering` verifies permutations and focus.

### Run alongside the other projects

All four projects default to port 8765. Use a separate terminal and port 8768
for this dashboard when running the collection together:

```powershell
python -m maternity_copilot serve --port 8768
```

Open **http://127.0.0.1:8768**; `/api/health` reports model readiness. Keep MCP
Shield on 8765, the Guardian on 8766, and Fursa on 8767. Alternatively,
`--port 0` selects an available port and prints its URL. Ports outside 0 through
65535 are rejected before model loading. If a port is occupied, choose another
rather than stopping an unrelated process.

## Safety and scope

- There are **no** free-text symptoms, names, health records, contact details, identifiers or clinical inputs.
- Catalog loading rejects undocumented fields and noncanonical resource IDs before any resource can be exported. This is structural validation, not clinical content review.
- The server rejects unknown keys, invalid enum values and invalid limits. This is a schema boundary, **not** a symptom detector or safety screening system.
- No triage, diagnosis, symptom prediction, treatment, medication dosing, health risk score, reassurance or individualized care.
- Resource bodies contain general topic descriptions and fixed questions for a qualified professional. They are demonstration content, not clinical guidance or authoritative health resources.
- Text similarity is not risk, a probability, confidence, quality, urgency or medical relevance. Lower-ranked resources can be unrelated to the chosen topic.
- The banner appears throughout the interface, printed questions and inference responses. Error responses repeat it. Emergency wording never invents a telephone number.
- Tests enforce rejection and catalog-only outputs; they do **not** establish clinical safety. Do not use this prototype to make decisions about care.

## HTTP interface

`GET /api/health` checks readiness; `GET /api/options` returns the bounded schema. `GET /` serves only the dashboard.
Readiness checks the live catalog fingerprint, returning 503 after catalog drift instead of advertising a stale model as ready; ready responses identify the catalog and resource count.
`POST /api/catalog` is read-only exact-filter browsing, not inference. Its
JSON object accepts optional stage/topic/format/focus, `offset` (nonnegative
integer) and `limit` (1–12, default 6). It returns ID-ordered fixed content,
total and next offset, rejecting extra fields/personal data and returning 503
if the authored catalog cannot be read. It shares inference's loopback,
media-type, framing, UTF-8, no-store and request-size controls.
`POST /api/batch` accepts a JSON list of one to eight bounded resource requests
within the same 2,048-byte envelope. All requests validate before one catalog
snapshot is read; any invalid item rejects the entire batch, without partial
results. `batch --input models\synthetic-requests.json` offers the same offline
behavior and byte bound. These are synthetic scenarios, not patient records,
cohorts or a bulk clinical interface.

`POST /api/resources` requires `Content-Type: application/json`:

```json
{"stage":"postpartum","topic":"access","format":"checklist","focus":"planning","limit":3}
```

Allowed selections:

| Field | Values |
|---|---|
| stage | pregnancy, postpartum |
| topic | appointments, support, wellbeing, feeding, access, care_team |
| format | guide, checklist |
| focus | planning, support |
| limit | optional integer 1–6, default 3 |

Responses include the notice, prototype/synthetic flags, score meaning and catalog resources with `retrieval_score`. Unknown keys, symptoms even as an extra field, arbitrary strings, missing fields and malformed JSON return HTTP 400 without echoing supplied values. Wrong media types return 415; unknown routes return 404. Requests over 2,048 bytes are rejected.
Resource responses also identify `catalog_sha256`. Selected dashboard
questions retain fixed source titles, IDs and 1-based numbers plus that
catalog hash in the printable list. Multiple matching sources are retained
without duplicate question text. Reset/invalidation clears this provenance;
browser scenario `provenance` verifies source/hash display and clearing. Unknown keys, symptoms even as an extra field, arbitrary strings, missing fields and malformed JSON return HTTP 400 without echoing supplied values. Wrong media types return 415; unknown routes return 404. Requests over 2,048 bytes are rejected.
The Print button requires explicit acknowledgment that the selected synthetic
questions were reviewed and are not a care plan or medical advice. Any
selection/removal/reorder resets acknowledgment. This is a reader check, not
professional content approval. Browser/OS printing can bypass the button; an
unreviewed warning remains visible in that print view. Browser scenario
`print-review` verifies gating, invalidation and print-media warning visibility. Unknown keys, symptoms even as an extra field, arbitrary strings, missing fields and malformed JSON return HTTP 400 without echoing supplied values. Wrong media types return 415; unknown routes return 404. Requests over 2,048 bytes are rejected.
The dashboard now offers an explicit 1–6 resource-count selection, default 3,
with the same pretransport validation and stale-view invalidation as other
preferences. Presets reset it to 3. `match --limit 1` and `explain --limit 1`
also honor the bounded count/cutoff; the latter still explains all candidates.
Browser scenario `limit` verifies counts and rejects fractional DOM values. Unknown keys, symptoms even as an extra field, arbitrary strings, missing fields and malformed JSON return HTTP 400 without echoing supplied values. Wrong media types return 415; unknown routes return 404. Requests over 2,048 bytes are rejected.
Before rendering any card, the dashboard checks the synthetic flags/notice,
catalog hash, complete fixed-resource schema, stage eligibility, unique IDs,
question arrays and finite similarity scores. Unexpected responses display
no partial cards and offer restore/train/restart recovery. Empty valid
responses explicitly say nothing about care needs/service availability and
offer a selection-review focus action. These structural checks do not
clinically approve content. Browser scenario `response` tests both paths. Unknown keys, symptoms even as an extra field, arbitrary strings, missing fields and malformed JSON return HTTP 400 without echoing supplied values. Wrong media types return 415; unknown routes return 404. Requests over 2,048 bytes are rejected.

The server binds only to `127.0.0.1`, validates Host and browser Origin, provides no cross-origin access, disables caching and request logs, and never writes requests to disk. Requests still pass through transient process memory. Printouts are the user's copies; browser/OS printing may save them. This lightweight development server is **not** production infrastructure or a privacy/compliance guarantee. Do not expose it publicly, use real health data or trust models from other people.
Duplicate Host, Origin and Content-Type headers are rejected rather than
interpreting only the first value. JSON media-type matching is case-insensitive. Requests still pass through transient process memory. Printouts are the user's copies; browser/OS printing may save them. This lightweight development server is **not** production infrastructure or a privacy/compliance guarantee. Do not expose it publicly, use real health data or trust models from other people.
GET targets must be origin-form paths; absolute URLs, network-path targets and
fragments return bounded JSON errors rather than aliasing the dashboard. Requests still pass through transient process memory. Printouts are the user's copies; browser/OS printing may save them. This lightweight development server is **not** production infrastructure or a privacy/compliance guarantee. Do not expose it publicly, use real health data or trust models from other people.
Unsupported methods return 405 with `Allow: GET, POST` and a nonreflective
JSON error. HEAD error responses omit the body while retaining its length;
HTTP parser failures also use the educational JSON error envelope. Requests still pass through transient process memory. Printouts are the user's copies; browser/OS printing may save them. This lightweight development server is **not** production infrastructure or a privacy/compliance guarantee. Do not expose it publicly, use real health data or trust models from other people.

## Model card

### Inspect content without a model

`python -m maternity_copilot browse --stage pregnancy --topic access --limit 6`
lists the fixed catalog in resource-ID order with optional bounded filters.
Use `--offset` and the returned `next_offset` for pagination. All filters are
exact, unlike retrieval preferences; an empty intersection is allowed.
No model is loaded and no similarity or clinical relevance is implied.
`compare-resources --stage pregnancy --resource access-guide --resource
access-checklist` presents two to four unique eligible resources in chosen
order, exact metadata contrasts and shared fixed questions. It needs no model
and requires human review; it never declares one resource clinically superior.
`related --stage pregnancy --resource access-guide --limit 3` uses fitted
document-to-document cosine similarity to explore other eligible catalog
entries. It excludes the source and incompatible stages and uses full
precision plus stable IDs for ordering. It is lexical browsing, not a care
pathway or a recommendation to undertake any treatment.
`catalog-audit` needs no model and prepares a structural human-review
inventory: per-resource hashes/token/question counts, shared-question
provenance and identical token-document groups. Passing structural checks
does not approve the content; the output explicitly records that this
demonstration catalog has not undergone clinical review.
`vocabulary --selection-only` audits bounded-selection token coverage in the
fitted vocabulary, with smoothed IDF, document frequencies and supporting
resource IDs. Without that flag it inventories all learned catalog terms.
Missing tokens are explicit; lexical coverage is not clinical knowledge.

`python -m maternity_copilot inspect` validates a fitted artifact and reports
per-document sparsity/norms, a byte-level artifact hash and a canonical
representation hash. Whitespace changes affect the first hash, not the second.
These diagnostics establish reproducibility only, not clinical fitness.
Artifact validation and its byte hash use the same bounded read snapshot:
replacing a file mid-inspection cannot attach a different file's hash.
Missing model files explain how to retrain with the same global `--model` path.
CLI file-permission/space failures and deeply nested local JSON exit with code
2, an actionable recovery message and the educational notice, not a traceback.

`explain` accepts the same four required selections as `match` and reports all
stage-eligible ranks at full precision, per-token cosine contributions, exact
preference matches and stage-excluded IDs. Contributions sum to the score.
Metadata matches explain preferences; they do not establish medical relevance.
Explanations also expose the top-score margin, cutoff gap, exact-score tie
groups and distinct scores that collide after six-decimal display rounding.
These diagnose numerical selection stability, not uncertainty about health.

**Model:** trainable, unsupervised TF-IDF vector-space retrieval baseline implemented in the Python standard library. It is not a generative model or a trained clinical predictor.

**Fitting:** lower-case tokenization with `[a-z_]+`, document frequency learned from the 12 catalog documents, smoothed IDF `log((1+N)/(1+df))+1`, sublinear term frequency `1+log(count)`, then L2 normalization. Each document combines its title, description and explicit topic/stage/format/focus metadata. Query vectors use only bounded selections with the learned IDF. Cosine similarity ranks compatible-stage documents; ties use stable catalog IDs. No topic hard-filter disguises the learned ranking.

**Artifacts:** JSON IDF vocabulary and document vectors, version and SHA-256 catalog fingerprint. Catalog changes require retraining. No unsafe pickle loading. Artifacts are excluded from version control.
Local catalog, benchmark and model JSON reject duplicate keys and nonfinite numbers rather than silently choosing one interpretation.
Readers cap bytes before parsing: 64 KiB each for catalog/benchmark, 2 MB for
models/evaluation reports and 16 KiB for question selectors. UTF-8 is required.
These are local prototype resource bounds, not protection for public hosting.

**Limitations:** lexical matching, English only, extremely small corpus, authored metadata, no semantic understanding or clinical judgment. Preferences influence ranking but do not guarantee every match follows that preference. The numerical score is a retrieval similarity only.

## Data and evaluation card

`maternity_copilot\data\catalog.json` contains 12 original synthetic descriptions, two per topic, and fixed appointment questions. Nothing is extracted from patient records, external clinical guidelines or copyrighted clinical material. Synthetic presets carry no real-person attributes.

`maternity_copilot\data\benchmark.json` contains twelve development and six held-out selection combinations, disjoint across splits. Binary relevance labels identify same-topic, stage-compatible resources. Format and focus preferences affect the rank, but the relevance labels do not measure preference satisfaction. There are no training query examples: this is **unsupervised catalog fitting**, not supervised prediction. Candidate documents necessarily remain in the retrieval index during evaluation. That is normal retrieval evaluation, not duplicate train/test query leakage.

`evaluate` calculates macro recall@k, binary nDCG@k and truncated MRR@k from actual rankings. It validates unique query combinations and stage-compatible labels. No score is prefilled or claimed here: run the command to obtain reproducible local numbers. These tiny, authored cases have direct metadata overlap and may give very high scores; that does not demonstrate real-user usefulness, robustness, generalization, safety or clinical outcomes. Held-out means query selections excluded from fitting/development cases, not independent patients or topics. Once inspected, this bundled split is no longer an untouched test set for future tuning. Any changed ranking should receive a new independent benchmark.

## Ethical considerations

Each evaluation uses one validated in-memory catalog snapshot for every query
and its manifest. Mid-run disk edits cannot mix old and new content in a report;
the next evaluation detects drift and requires retraining.
Benchmark cases must contain exactly the four bounded selections and `relevant`
resource IDs; free-form metadata is rejected, not retained in reports.
Evaluation also reports precision@k (hits divided by requested k, including
empty slots) and truncated average precision@k (sum of precision at each hit,
divided by `min(k, relevant_count)`), with macro MAP@k. These expose irrelevant
tail matches that recall alone can hide.
Each case identifies missed relevant IDs with their full-list ranks, irrelevant
returned IDs, eligible candidate count and the maximum recall possible at k.
This separates cutoff capacity from ranking failures without redefining recall.
Evaluation reports carry schema version 1, the educational notice, canonical
model hash and a canonical report hash computed over every field except
`report_sha256` itself. Identical runs produce identical reports, with no
timestamp or path-dependent identifiers.
`evaluate --output models\held-out-report.json` saves the same report it prints
using an atomic, flushed JSON publication. A failed write preserves the prior
file; model and packaged-data destinations are rejected. Reports contain only
authored synthetic cases. Store them under ignored `models\` if not intended
for version control.

`compare --before models\before.json --after models\after.json` inspects saved
reports without loading a model. It verifies hashes, exact bounded schemas,
rank uniqueness/stage eligibility and recomputes metrics before reporting
deltas and changed cases. Both reports must use the current synthetic catalog
and benchmark, the same split and k. It allows different model hashes, but does
not load those models or establish statistical/clinical significance. A report
hash is an integrity check, not an author signature.
Metric reconciliation allows at most `1e-12` absolute arithmetic difference
for cross-platform logarithm roundoff; report integrity hashes remain exact,
and ranking still uses full precision. Overflowing JSON exponents such as
`1e999` are rejected as nonfinite, not silently accepted as infinity.
Comparisons include per-case metric deltas and entered/left IDs. For scripted
retrieval checks, add `--fail-on-regression recall_at_k ndcg_at_k` and optional
`--tolerance 0.01` (absolute metric units). It prints the comparison/gate and
exits 1 on aggregate degradation beyond tolerance plus `1e-12` arithmetic
allowance, 0 on pass, or 2 on invalid input. This is **not a clinical safety or
deployment gate**; aggregate passes can conceal individual case regressions.
Add `--per-case` to require that every changed authored case also stays within
the same tolerance for selected metrics. Failed cases are identified by
bounded selections, preventing improvements elsewhere from hiding a local
ranking regression. This remains a retrieval check, never a care-safety gate.

`coverage` needs no model: it audits the 48 possible bounded selections against
the 18 authored benchmark cases, lists unrepresented combinations, counts
relevance labels per resource and reports stage/topic content gaps. Coverage
here means schema/catalog coverage, never population or clinical coverage.

`sweep --k 3` runs all 48 bounded selection combinations on one catalog
snapshot. It derives same-topic, stage-compatible labels from metadata and
reports recall and top-result format/focus/topic match counts. This is a
metadata stress check, **not a new independent benchmark or held-out result**;
derived labels cannot establish generalization, safety or clinical usefulness.
Six added development cases include conflicting format/focus preferences and
an appointment format unavailable for the selected stage. Labels remain
same-topic eligible IDs, not preference or clinical judgments; the original
six held-out cases were not changed or promoted into development.

`sensitivity` takes the four required selections plus `--field stage` (or
topic/format/focus) and optional `--limit 1..6`. It varies only that enum, reports
top-list entries/exits and retained rank shifts. It performs no free-text
perturbation, medical counterfactual or care recommendation.

`plan --stage pregnancy --resource access-guide --resource support-guide`
needs no model and assembles fixed questions from one to six unique,
stage-compatible resource IDs. Duplicate question text is merged with all
source resource/question numbers retained. The JSON marks human review as
required: this is an educational conversation list, **not a care plan**.
Alternatively, `plan --stage pregnancy --question access-guide:2 --question
support-guide:1` selects exact 1-based question numbers, preserving the chosen
order. Up to twelve unique picks from at most six eligible resources are
accepted; free-text questions, unknown numbers and duplicates are rejected.
For synthetic demonstrations only, `plan ... --output models\questions.json`
atomically stores bounded selectors and a catalog/hash manifest, not question
text or personal notes. `plan-read --input models\questions.json` reconstructs
the authored questions after strict integrity/schema checks. Catalog drift
requires a fresh human review and selection; hashes are not signatures.
`evaluate-groups --by topic --split held_out --k 3` reports macro metrics and
case counts for each bounded selection value. Empty groups use null, not zero.
Weighted group metrics reconcile with the original report. These are tiny
authored selection groups, not patient subgroups or a fairness assessment.
`evaluate-curve --split held_out` evaluates every supported cutoff, 1–6, on
one catalog/benchmark snapshot. It reports all five metrics, mean returned
count and recall capacity, showing the recall/irrelevant-tail trade-off rather
than choosing a supposedly medically optimal list length.
`evaluate-baselines --split held_out --k 3` contrasts TF-IDF recall, nDCG and
precision with two deterministic baselines: eligible IDs alphabetically, and
same-topic metadata first then ID. The second deliberately uses the same
metadata underlying authored labels, making their triviality visible. Neither
baseline establishes learning, semantic understanding or clinical outcomes.
Unlike the dashboard's ephemeral state, these explicit files persist until
you delete them. Never put personal data in them.
`plan ... --text` and `plan-read ... --text` print a readable numbered
conversation list with per-question sources, catalog hash, human-review
requirement and the safety notice at both ends. Redirect it to a local text
file if needed. The renderer refuses modified question text; this is not a
record of a real appointment or a clinically approved document.
`plan-merge --input models\a.json --input models\b.json` merges two to four
validated synthetic selector files for the same stage, deduplicating picks
and preserving first occurrence. The six-resource/twelve-pick bounds still
apply. Optional `--output` saves a selector file; `--text` prints the list.
Merging does not remove the human-review requirement.
`plan-diff --before models\a.json --after models\b.json` reviews two validated
selector files, separating added/removed fixed picks, retained-order changes
and stage changes. It does not interpret changes as clinical progress, care
needs or a real appointment history.
`plan-edit --input models\a.json --remove access-guide:2` removes only existing
fixed picks. Repeated `--order catalog-id:number` arguments must specify a full
permutation of the retained picks. At least one pick must remain; no stage or
free-text editing is offered. Output is read-only unless `--output` explicitly
saves it, and `--text` renders the same human-review conversation list.

Health-related branding and tidy numerical rankings can encourage over-trust. The product limits output to fixed educational prompts, disallows health narratives and labels every demo clearly. These controls reduce scope, not establish safety. Access, language, disability, literacy and local service availability differ; the English demo cannot represent worldwide needs. A question about a service does not imply that service exists in the user's location. No personalized service availability is inferred.

## From working core to an accessible care-preparation layer

These are proposed review gates, **not completed safety reviews**:

1. Qualified maternity professionals and patient/community representatives review all proposed content, wording and failure modes before any real-world pilot.
2. Introduce versioned, clinician-approved educational content with provenance, jurisdiction, approval dates and withdrawal mechanisms. Keep diagnosis, triage and treatments out of scope.
3. Co-design multilingual and accessible material with professional translators and local clinicians; evaluate comprehension, retrieval relevance, cultural fit and harmful omissions using independent cases.
4. Explore human care coordination only through reviewed, explicit consent pathways to actual care teams. Do not automate care decisions or invent service availability.
5. Before any deployment, complete privacy, security, accessibility and regulatory assessments, abuse testing and monitoring plans. Define escalation to qualified humans and appropriate local emergency information from verified sources, without building symptom triage.

The current repository implements none of these clinical deployment gates.

## Project layout

```text
.github\workflows\ci.yml           Python test and evaluation matrix
maternity_copilot\__main__.py      CLI
maternity_copilot\core.py          Model fitting, bounded retrieval, metrics
maternity_copilot\server.py        Local HTTP inference and dashboard serving
maternity_copilot\dashboard.html   Self-contained Clawpilot-themed dashboard
maternity_copilot\data\catalog.json
maternity_copilot\data\benchmark.json
tests\test_project.py              Model, safety-boundary and actual HTTP tests
pyproject.toml                    Optional packaging; no runtime dependencies
```

CI exercises persistence, stale-model rejection, learned preference relevance, split uniqueness, independently recomputed metrics, every bounded input combination, invalid/symptom inputs and real HTTP inference with origin/size controls. Tests create isolated files under ignored `models\` and remove them afterward. Runtime model artifacts are local only.
CI runs on Windows and Ubuntu with Python 3.10, 3.13 and 3.14, including CLI
artifact inspection, saved-report self-comparison with per-case regression
checks and fixed-question selector round-trip/plaintext rendering. Tests create isolated files under ignored `models\` and remove them afterward. Runtime model artifacts are local only.
Optional real-browser checks use Node 22+ and an explicitly isolated Chromium
profile with an ephemeral CDP port: `node tests\browser_check.cjs
http://127.0.0.1:APP_PORT CDP_PORT cancel`. This adds no runtime dependency.
The check drives Escape and releases a forced late real-backend response,
verifying cancellation, busy state, focus, loopback-only requests and no storage. Tests create isolated files under ignored `models\` and remove them afterward. Runtime model artifacts are local only.
