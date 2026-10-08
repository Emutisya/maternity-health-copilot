# Maternity Health Copilot | AI for Health

### Make every care conversation easier to prepare for.

**Maternity Health Copilot is a local-first educational navigation and
appointment preparation system for pregnancy and postpartum.** It turns bounded
stage, topic and format preferences into ranked educational conversation
starters and a printable question list for discussion with a qualified
healthcare professional.

[![CI](https://github.com/Emutisya/maternity-health-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/Emutisya/maternity-health-copilot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

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

Python 3.10+ is the only runtime requirement. No installs, API keys, network calls, downloaded weights or CDNs are needed. From this directory in PowerShell:

```powershell
python -m maternity_copilot train
python -m maternity_copilot evaluate --split held_out --k 3
python -m maternity_copilot match --stage pregnancy --topic appointments --format guide --focus planning
python -m maternity_copilot serve
```

Open **http://127.0.0.1:8765**. Stop with Ctrl+C. Use `serve --port 8766` if that port is occupied, and open the corresponding loopback URL. Models are regenerated locally and ignored by Git. Global `--model` belongs **before** the subcommand:

```powershell
python -m maternity_copilot --model models\demo.json train
python -m maternity_copilot --model models\demo.json serve
python -m unittest discover -s tests -v
```

The packaged, single-file HTML has all its styles and scripts inline. Opening it directly shows the interface but cannot perform inference: serve it through Python. Synthetic presets, bounded topic/preferences, resource cards, selected appointment questions and an optional print view are available. Changing selections clears old matches. Refresh/reset clears the question list; no browser storage is used.

## Safety and scope

- There are **no** free-text symptoms, names, health records, contact details, identifiers or clinical inputs.
- The server rejects unknown keys, invalid enum values and invalid limits. This is a schema boundary, **not** a symptom detector or safety screening system.
- No triage, diagnosis, symptom prediction, treatment, medication dosing, health risk score, reassurance or individualized care.
- Resource bodies contain general topic descriptions and fixed questions for a qualified professional. They are demonstration content, not clinical guidance or authoritative health resources.
- Text similarity is not risk, a probability, confidence, quality, urgency or medical relevance. Lower-ranked resources can be unrelated to the chosen topic.
- The banner appears throughout the interface, printed questions and inference responses. Error responses repeat it. Emergency wording never invents a telephone number.
- Tests enforce rejection and catalog-only outputs; they do **not** establish clinical safety. Do not use this prototype to make decisions about care.

## HTTP interface

`GET /api/health` checks readiness; `GET /api/options` returns the bounded schema. `GET /` serves only the dashboard.

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

The server binds only to `127.0.0.1`, validates Host and browser Origin, provides no cross-origin access, disables caching and request logs, and never writes requests to disk. Requests still pass through transient process memory. Printouts are the user's copies; browser/OS printing may save them. This lightweight development server is **not** production infrastructure or a privacy/compliance guarantee. Do not expose it publicly, use real health data or trust models from other people.

## Model card

**Model:** trainable, unsupervised TF-IDF vector-space retrieval baseline implemented in the Python standard library. It is not a generative model or a trained clinical predictor.

**Fitting:** lower-case tokenization with `[a-z_]+`, document frequency learned from the 12 catalog documents, smoothed IDF `log((1+N)/(1+df))+1`, sublinear term frequency `1+log(count)`, then L2 normalization. Each document combines its title, description and explicit topic/stage/format/focus metadata. Query vectors use only bounded selections with the learned IDF. Cosine similarity ranks compatible-stage documents; ties use stable catalog IDs. No topic hard-filter disguises the learned ranking.

**Artifacts:** JSON IDF vocabulary and document vectors, version and SHA-256 catalog fingerprint. Catalog changes require retraining. No unsafe pickle loading. Artifacts are excluded from version control.

**Limitations:** lexical matching, English only, extremely small corpus, authored metadata, no semantic understanding or clinical judgment. Preferences influence ranking but do not guarantee every match follows that preference. The numerical score is a retrieval similarity only.

## Data and evaluation card

`maternity_copilot\data\catalog.json` contains 12 original synthetic descriptions, two per topic, and fixed appointment questions. Nothing is extracted from patient records, external clinical guidelines or copyrighted clinical material. Synthetic presets carry no real-person attributes.

`maternity_copilot\data\benchmark.json` contains six development and six held-out selection combinations, disjoint across splits. Binary relevance labels identify same-topic, stage-compatible resources. Format and focus preferences affect the rank, but the relevance labels do not measure preference satisfaction. There are no training query examples: this is **unsupervised catalog fitting**, not supervised prediction. Candidate documents necessarily remain in the retrieval index during evaluation. That is normal retrieval evaluation, not duplicate train/test query leakage.

`evaluate` calculates macro recall@k, binary nDCG@k and truncated MRR@k from actual rankings. It validates unique query combinations and stage-compatible labels. No score is prefilled or claimed here: run the command to obtain reproducible local numbers. These tiny, authored cases have direct metadata overlap and may give very high scores; that does not demonstrate real-user usefulness, robustness, generalization, safety or clinical outcomes. Held-out means query selections excluded from fitting/development cases, not independent patients or topics. Once inspected, this bundled split is no longer an untouched test set for future tuning. Any changed ranking should receive a new independent benchmark.

## Ethical considerations

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
LICENSE                           MIT
```

CI exercises persistence, stale-model rejection, learned preference relevance, split uniqueness, independently recomputed metrics, every bounded input combination, invalid/symptom inputs and real HTTP inference with origin/size controls. Tests create isolated files under ignored `models\` and remove them afterward. Runtime model artifacts are local only.
