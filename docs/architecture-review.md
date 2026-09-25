# DSister Quote Workflow — Final Architecture Plan (v2)

> **Implementation status (2026-09-21):** the vertical slice in §6 is built and tested —
> `contracts/`, `catalog/`, `pricing/` (+ `service.price_request`), `explain/` (fallback + LLM
> path with validation), `quotation/`, `storage/`, `workflow/`, the Streamlit portal, and the
> `build_db` / `seed_cases` / `run_case` scripts. `intake/` (Jenny) and `evaluation/` +
> `observability/` wiring (Rea) are the open modules; their seams are `workflow.submit_request`
> and `SqliteCaseStore` / `pricing.service.price_request`. Tracing decorators were deliberately
> **not** carried over from the POC's catalog/orchestrator code — span placement is Rea's call.

## Context

The POC (`pricing agent_YG POC`) is a working single-request pricing pipeline: deterministic resolution → deterministic pricing engine → one grounded LLM "advisor" call, with Langfuse tracing and a golden eval. It has no persisted case, no queue, no human decision, no quotation.

`ds-sisters-quote-workflow` (currently only `docs/architecture-review.md`, not yet `git init`) becomes the shared team repo for a small, engineering-oriented **RFQ → QuoteCase → pricing → reviewer portal → quotation** workflow built by three people in about a week. This is the revised plan after the v1 review; it incorporates the twelve decisions from that review. The POC stays read-only.

Changes from v1, in one glance: intake internals are no longer prescribed (contract = a complete `QuoteRequest`); `Address` + billing/shipping/delivery date added to `QuoteRequest` and `Quotation`; `cases` + `case_events` persistence; six statuses (no `PROCESSING`); deterministic `rationale` on `PricingDecision`, separate from the LLM `ReviewerSummary`; explicit out-of-scope list; dependency rules downgraded to guidance; contracts trimmed.

---

## 0. MVP scope

The product is exactly:

```
Email / RFQ → Intake → complete QuoteRequest → Pricing → ReviewerSummary
→ persisted QuoteCase → Reviewer Portal → Human decision → Quotation → Evaluation
```

**Out of scope** (do not build, do not leave hooks for): inventory / stock lookup / warehouse allocation, freight / carrier / shipping optimisation, CRM / ERP integration, authentication, async workers / queues, generic plugin or pipeline frameworks, PDF-driven architecture.
Static demo fields such as `estimated_lead_time` or an availability note may appear on a quotation; there is no inventory subsystem behind them.

---

## 1. Final repository tree

```
ds-sisters-quote-workflow/
├── CLAUDE.md                          # §6
├── README.md
├── pyproject.toml                     # package `quote_workflow`; requires-python >= 3.12
├── requirements.txt                   # runtime pins for Streamlit Cloud
├── .env.example
├── .gitignore
├── docs/
│   └── architecture-review.md         # this document
├── config/
│   └── policy.yaml                    # from POC + `version:` key
├── data/
│   ├── reference/                     # POC data/raw/*.csv (customers, products, aliases, deals, sales_history)
│   ├── samples/
│   │   ├── requests.json              # sample structured QuoteRequests → seed cases (slice input)
│   │   └── inbox/                     # sample RFQ emails — intake's demo input (Jenny populates)
│   ├── eval/                          # golden cases (Rea)
│   └── db/                            # generated: catalog.db, cases.db (git-ignored)
├── src/quote_workflow/
│   ├── __init__.py
│   ├── config.py                      # paths, env vars, model ids
│   ├── contracts/                     # SHARED — §2 only, nothing else
│   │   ├── __init__.py                # re-exports everything below
│   │   ├── enums.py                   # CaseStatus, ReviewAction, PricingStatus, ResolutionStatus
│   │   ├── common.py                  # Address
│   │   ├── source.py                  # RfqSource
│   │   ├── quote_request.py           # QuoteRequest, QuoteLine
│   │   ├── pricing.py                 # PricingDecision, LineDecision, Lever
│   │   ├── review.py                  # ReviewerSummary, ReviewDecision
│   │   ├── quotation.py               # Quotation, QuotationLine
│   │   ├── case.py                    # QuoteCase, CaseEvent
│   │   └── store.py                   # CaseStore Protocol
│   ├── catalog/                       # reference data: SQLite build, lookups, optional resolve helper
│   │   ├── schema.sql, build.py, connection.py
│   │   ├── types.py                   # CustomerInfo, ProductInfo, Deal, SaleRecord (internal)
│   │   ├── repository.py              # get_/find_/search_ lookups (POC tools)
│   │   └── resolution.py              # resolve(conn, QuoteRequest) -> QuoteRequest — a helper, not a mandated stage
│   ├── intake/                        # JENNY — RfqSource -> complete QuoteRequest (internals are hers)
│   ├── pricing/                       # deterministic
│   │   ├── policy.py, engine.py, types.py   # POC, internal
│   │   └── service.py                 # price_request(conn, request, policy, as_of) -> PricingDecision
│   ├── explain/                       # LLM reviewer summary, grounded + validated, with fallback
│   │   ├── prompts.py, facts.py, validate.py, fallback.py, summarize.py
│   ├── quotation/
│   │   └── render.py                  # build_quotation(case) -> Quotation (structured + markdown body)
│   ├── storage/
│   │   ├── schema.sql                 # cases, case_events
│   │   └── sqlite_store.py            # SqliteCaseStore(CaseStore)
│   ├── workflow/                      # the composer
│   │   ├── status.py                  # allowed transitions
│   │   ├── pipeline.py                # create_case_from_source, submit_request, price_and_summarize
│   │   └── review.py                  # apply_review(case_id, ReviewDecision)
│   ├── observability/                 # REA — tracing setup/helpers
│   └── evaluation/                    # REA — never imported by the pipeline
├── app/                               # Streamlit portal (YINPING)
│   ├── streamlit_app.py               # entry: optional access gate, "view as", navigation
│   ├── views/queue.py                 # My Queue / All / Needs Info / Completed
│   ├── views/case_detail.py           # layout in §4.3
│   ├── views/trace.py                 # Technical Trace: events, timings, trace link
│   └── ui.py                          # money/status formatting helpers
├── scripts/
│   ├── build_db.py                    # catalog only — never touches cases.db
│   ├── seed_cases.py                  # data/samples/requests.json → cases
│   ├── run_case.py                    # (re)run pricing+summary for one/all cases, print result
│   ├── ingest_inbox.py                # (Jenny) inbox → cases
│   └── run_eval.py                    # (Rea)
└── tests/
    ├── conftest.py                    # tmp catalog db + tmp case store fixtures
    ├── contracts/ catalog/ pricing/ explain/ quotation/ storage/ workflow/
    ├── intake/                        # Jenny
    └── evaluation/                    # Rea
```

---

## 2. Final shared contracts (`contracts/`)

Only true cross-module shapes live here. Pydantic v2, `StrEnum`, JSON round-trippable; new fields are Optional with defaults so stored cases keep loading. Module-internal types (`catalog/types.py`, `pricing/types.py`) stay in their modules.

### Enums
```python
class CaseStatus(StrEnum):       RECEIVED, NEEDS_INFO, READY_FOR_REVIEW, REWORK_REQUESTED, APPROVED, REJECTED, FAILED
class ReviewAction(StrEnum):     APPROVE, REJECT, REQUEST_INFO
class ReworkTarget(StrEnum):     PRICING, EXPLAIN     # portal work; no INTAKE - see §4.1
class QuotationFormat(StrEnum):  MARKDOWN, HTML, PDF  # portal work; which renderer produced a body
class ResolutionStatus(StrEnum): RESOLVED, MISSING, NOT_FOUND, AMBIGUOUS     # POC
class PricingStatus(StrEnum):    APPROVED, COUNTER_RECOMMENDED, ESCALATION_REQUIRED, INSUFFICIENT_DATA  # POC
```

### `Address` (`common.py`)
`name: str | None, line1: str, line2: str | None, city: str, region: str | None, postal_code: str | None, country: str`, plus `as_text()` for rendering.

### `RfqSource` (`source.py`) — what came in
`source_id, received_at, sender, subject, body_text, attachment_names: list[str] = []`.
Minimal on purpose: enough for the portal's "Original RFQ" panel and for intake to work from. Intake decides what it does with attachments.

### `QuoteRequest` / `QuoteLine` (`quote_request.py`) — the normalized commercial request
POC model extended with the fields the review requires:

```python
class QuoteLine(BaseModel):
    product_name: str | None; product_id: int | None; product_status: ResolutionStatus = MISSING
    candidates: list[str] = []
    quantity: PositiveInt | None
    requested_unit_price: PositiveFloat | None; competitor_price: PositiveFloat | None
    @property is_priceable -> product RESOLVED and quantity set

class QuoteRequest(BaseModel):
    customer_name, customer_id, customer_status: ResolutionStatus = MISSING, customer_candidates
    billing_address: Address | None; shipping_address: Address | None
    requested_delivery_date: date | None
    contract_months: int | None; requested_discount_pct: float | None
    lines: list[QuoteLine]
    source_text: str | None; notes: str | None
    clarification_questions: list[str] = []          # intake's questions for the customer, display only
    def missing_fields() -> list[str]                # the standard completeness check (below)
    @property is_complete -> not missing_fields()
```

**Completeness rule** (one place, in the contract, so intake, workflow and tests agree): a request is complete when the customer is RESOLVED, there is ≥1 line, every line is priceable, and billing and shipping addresses are present. `requested_delivery_date` is optional (the quotation shows "requested / estimated"). `missing_fields()` returns the POC's `issues()` strings plus `"billing_address"` / `"shipping_address"`.

Where the addresses come from — email, attachment, customer master data, or a clarification reply — is intake's business; downstream never asks.

### `PricingDecision` (`pricing.py`) — deterministic, final
```python
class Lever(BaseModel):          id, kind, description, unit_price, threshold: int | None
class LineDecision(BaseModel):   # POC LineRecommendation +
    ... list/floor/deal/ladders/recommended/requested/counter/final/line_total/discount/margin/history/levers ...
    rationale: list[str]         # deterministic sentences: "customer-specific 10% deal (#1) applied", "6% volume tier (100+)", "requested $x is below the margin floor; counter $y"
class PricingDecision(BaseModel):
    status: PricingStatus; issues: list[str]; lines: list[LineDecision]; unresolved_lines: int
    total_list_value, total_quoted_value, total_discount_pct, blended_margin_pct
    as_of_date: date; policy_version: str; priced_at: datetime
    warnings: list[str]          # deterministic reviewer-facing flags (escalations, floor hits, expired deals)
```
Nothing downstream may change a number here. `rationale` and `warnings` are what the portal's **Pricing Rationale** and **Warnings** sections show even when no LLM is available.

### `ReviewerSummary` (`review.py`) — LLM, validated, optional
```python
class ReviewerSummary(BaseModel):
    summary: str                     # 2–4 sentences: what was decided and why it matters
    rationale: list[str]             # rules / discounts / deals used, in the reviewer's language
    warnings: list[str]              # risks, thin margins, expired deals the customer may expect
    attention_items: list[str]       # what the reviewer should look at before approving
    draft_reply: str | None          # customer-facing draft, no internal figures
    generated_by: Literal["llm", "fallback"]; model: str | None; rejected_reason: str | None
```

### `ReviewDecision` (`review.py`) — the human's action
`action: ReviewAction, reviewer: str, comment: str | None, decided_at: datetime`. No price overrides in the MVP.

### `Quotation` / `QuotationLine` (`quotation.py`)
```python
class QuotationLine(BaseModel):  product_name, quantity, unit_price, line_total
class Quotation(BaseModel):
    quote_number, case_id, quote_date: date, valid_until: date
    customer_name; billing_address: Address; shipping_address: Address
    requested_delivery_date: date | None; estimated_delivery_note: str | None   # static/demo text
    lines: list[QuotationLine]; subtotal; discount_amount: float | None; total
    payment_terms: str | None; notes: str | None
    body: str                        # archival rendering shown/downloaded in the portal
    body_format: QuotationFormat     # which renderer produced it (markdown today)
```
Structured model first; markdown render second; PDF only after the flow works, and only as a renderer over this model.

**Renderers** (added with the portal work): the model is format-neutral, and a format is a `Renderer` — a render function plus a media type and file extension — in `quotation/renderers.py`. `build_quotation(case, renderer=DEFAULT)` stores what the renderer produced. Adding HTML or PDF is a new render function and one `Renderer` entry; `contracts` and `workflow` do not change.

### `QuoteCase` / `CaseEvent` (`case.py`) — the persisted case record
```python
class CaseEvent(BaseModel):
    at: datetime; stage: str; message: str; level: Literal["info","warning","error"] = "info"
    from_status: CaseStatus | None; to_status: CaseStatus | None

class QuoteCase(BaseModel):
    schema_version: int = 1
    case_id: str; status: CaseStatus; created_at; updated_at; assigned_to: str | None
    source: RfqSource | None; request: QuoteRequest | None
    pricing: PricingDecision | None; summary: ReviewerSummary | None
    review: ReviewDecision | None; quotation: Quotation | None
    evaluation_ref: str | None       # id/URL of an evaluation record; shape owned by evaluation
    trace_id: str | None
    events: list[CaseEvent] = []     # hydrated by the store on read; not part of the JSON blob
```

### `CaseStore` (`store.py`)
```python
class CaseStore(Protocol):
    def create(self, case: QuoteCase, event: CaseEvent) -> QuoteCase
    def get(self, case_id: str) -> QuoteCase                       # with events
    def save(self, case: QuoteCase, event: CaseEvent | None = None) -> None   # state + optional appended event, one transaction
    def list(self, status: CaseStatus | None = None, assigned_to: str | None = None) -> list[QuoteCase]  # without events
    def events(self, case_id: str) -> list[CaseEvent]
```

Evaluation shapes (`EvaluationResult`, golden format) are Rea's; if one becomes cross-module she adds `contracts/evaluation.py`.

---

## 3. QuoteCase and persistence design

- **`QuoteRequest`** = what pricing consumes. **`QuoteCase`** = the case record. Feature modules take typed inputs and return typed outputs; `workflow/` attaches outputs to the case and persists.
- Two tables in `data/db/cases.db` (separate file from `catalog.db`, so rebuilding reference data never wipes cases):

```sql
cases (
  case_id TEXT PRIMARY KEY, status TEXT NOT NULL, assigned_to TEXT,
  customer_name TEXT, total_quoted_value REAL,          -- denormalised for the queue view
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  schema_version INTEGER NOT NULL, case_json TEXT NOT NULL   -- QuoteCase minus events
)
case_events (
  event_id INTEGER PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases,
  at TEXT NOT NULL, stage TEXT NOT NULL, level TEXT NOT NULL,
  from_status TEXT, to_status TEXT, message TEXT NOT NULL
)
```

- `cases` is current state; `case_events` is append-only history (`CASE001 RECEIVED → NEEDS_INFO → READY_FOR_REVIEW → APPROVED`). No event sourcing: the case is never rebuilt from events.
- The queue reads `cases` columns only; the Technical Trace reads `case_events`.
- Schema changes during the week: bump `schema_version`, delete `cases.db`, reseed. No migrations.
- Streamlit Community Cloud disk is ephemeral → cases reset on redeploy; `streamlit_app.py` seeds sample cases when the store is empty. Fine for a demo.

---

## 4. Workflow

### 4.1 Statuses and transitions (`workflow/status.py`)
```
RECEIVED ──(intake incomplete)──► NEEDS_INFO ──(request completed)──► READY_FOR_REVIEW
RECEIVED ──(intake complete + priced)────────────────────────────────► READY_FOR_REVIEW
RECEIVED / NEEDS_INFO ──(unhandled error)──► FAILED ──(re-run)──► RECEIVED
READY_FOR_REVIEW ──APPROVE──► APPROVED      READY_FOR_REVIEW ──REJECT──► REJECTED
READY_FOR_REVIEW ──REQUEST_INFO──► NEEDS_INFO
READY_FOR_REVIEW ──rework requested──► REWORK_REQUESTED ──rework run──► READY_FOR_REVIEW
```
`READY_FOR_REVIEW` ⇔ `request.is_complete` **and** `pricing` exists. No `PROCESSING`: the pipeline runs synchronously in-process (script or Streamlit callback); add it only if a background runner appears.

**Rework** (added with the portal work). `REWORK_REQUESTED` is a reviewer sending the case back to one of *our* stages; `NEEDS_INFO` is waiting on the customer. `ReworkTarget` is `PRICING` or `EXPLAIN` — deliberately no `INTAKE`, because a case only reaches review once the request is complete, so extraction that is wrong rather than missing is corrected by the reviewer through `workflow.apply_edit`, and most seeded cases carry no `source` to re-extract. The case row is the work item: `store.list(status=REWORK_REQUESTED)` is the entire discovery mechanism, so there is no work-item table. Two-step by design (`request_rework` then `run_rework`) so the state is observable and survives a refresh; `run_rework` re-runs `price_and_summarize`, so a reworked case never shows a stale number. `scripts/run_rework.py` demonstrates an out-of-process component discovering and completing the work through the same store.

### 4.2 Entry points (`workflow/pipeline.py`, `workflow/review.py`)
```python
create_case_from_source(store, source: RfqSource) -> QuoteCase
    # RECEIVED; assigned_to = default reviewer. Then intake.run_intake(source, conn) -> QuoteRequest
    # (Jenny's function; stubbed until merged), then submit_request(...)

submit_request(store, conn, case_id, request: QuoteRequest) -> QuoteCase
    # THE seam. Used by intake, by seed_cases.py, by evaluation, by any future "provide info" form.
    # if not request.is_complete → status NEEDS_INFO, event lists missing_fields + clarification_questions
    # else → price_and_summarize(...)

price_and_summarize(store, conn, case_id) -> QuoteCase
    # pricing.service.price_request(conn, case.request, policy, as_of)  → case.pricing
    # explain.summarize(case.request, case.pricing, client)              → case.summary (fallback on any failure)
    # status READY_FOR_REVIEW; any exception → FAILED with the error in the event

apply_review(store, case_id, decision: ReviewDecision) -> QuoteCase
    # validates transition; APPROVE → quotation.build_quotation(case) → case.quotation; save + event
```
The order resolve/complete → price → explain is written once, here. Pricing is complete and final before the LLM is contacted; a missing API key never changes a price or a status.

### 4.3 Case detail layout (`app/views/case_detail.py`)
```
Header: case id · customer · status badge · assigned to
Request / customer information      Billing address · Shipping address · Requested delivery date
Items / quantities                  (product, qty, requested price if any)
Pricing Result                      per line: list, deal/ladders, recommended, requested, counter, final, margin; totals
Pricing Rationale                   PricingDecision.lines[].rationale (deterministic)
AI Reviewer Summary                 ReviewerSummary.summary / rationale / warnings / attention_items (+ "fallback" badge)
Warnings / Missing Information      PricingDecision.warnings + request.missing_fields() + clarification_questions
[Approve] [Edit] [Ask AI to Revise] [Reject]   → workflow.apply_review / apply_edit / request_rework
Draft quote / Quotation             preview before a decision; the stored quotation after approval, + download
Tab: Technical Trace                case_events, stage timings, Langfuse trace link
```
Queue views (navigation screens under `app/screens/`): My Queue (assigned_to = viewer), All Cases, Needs Attention, Completed, Admin / Monitoring. Each queue has a keyword search and status / assignee / customer / updated filters, all applied in Python over the store's list. "Needs Attention" is derived, not stored: open cases that are NEEDS_INFO, FAILED or REWORK_REQUESTED, or whose pricing needs a decision or carried warnings. Admin reports case counts by status, failed cases with their error events, the schema and policy versions, and catalog record counts. "View as" segmented control replaces roles/auth.

### 4.4 Original RFQ
Shown from `case.source` when present; cases seeded from structured requests have `source = None` and show the request only.

---

## 5. POC migration mapping (updated)

| POC | Action | New location | Notes |
|---|---|---|---|
| `pricing/engine.py` | reuse as-is | `pricing/engine.py` | pure; 49 tests port with import renames |
| `pricing/policy.py`, `config/policy.yaml` | reuse as-is | `pricing/policy.py`, `config/policy.yaml` | add `version:` → `PricingDecision.policy_version` |
| `pricing/types.py` | reuse, split | `pricing/types.py` (LinePricing, QuotePricing, HistoricalReference, Lever), `catalog/types.py` (CustomerInfo, ProductInfo, Deal, SaleRecord) | both internal, not contracts |
| `models/enums.py` | reuse | `contracts/enums.py` | + `CaseStatus`, `ReviewAction` |
| `models/quote_request.py` | reuse + extend | `contracts/quote_request.py` | + addresses, delivery date, `missing_fields()`, `is_complete`; drop `single()` |
| `models/quote_recommendation.py` | split | `contracts/pricing.py` (`LineRecommendation`→`LineDecision`, `LeverOut`→`Lever`, totals→`PricingDecision`), `contracts/review.py` (`AdvisorNote`→`ReviewerSummary`, reshaped) | `QuoteRecommendation` bundle disappears |
| `db/*`, `data/raw/*.csv` | reuse as-is | `catalog/`, `data/reference/` | catalog.db only |
| `tools/agent_tools.py` | reuse, rename | `catalog/repository.py` | lookups + token search; tracing decorators stay (Rea may adjust) |
| `agent/resolution.py` | reuse | `catalog/resolution.py` | offered to intake and to `seed_cases.py`; not a mandated stage |
| `agent/advisor.py` | refactor | `explain/` | keep `build_facts`, number-grounding + leakage `validate`, `deterministic_summary` (→ fallback that fills `ReviewerSummary` from `PricingDecision.rationale/warnings`); rewrite prompt for a *reviewer* audience with the §2 output schema; drop lever-id selection |
| `agent/pricing_agent.py` | split three ways | `_price_all_lines` → `pricing/service.py` (adds `rationale`, `warnings`, `policy_version`); advisor call + fallback → `explain/summarize.py`; ordering + tracing → `workflow/pipeline.py` | do not port as one function |
| `agent/config.py`, `paths.py` | merge | `config.py` | |
| `observability/tracing.py` | hand to Rea | `observability/` | `configure()`/`flush()` are a fine start; add `case_id` to trace metadata |
| `eval/evaluators.py` (deterministic checks), `data/eval/golden_cases.json` | hand to Rea | `evaluation/`, `data/eval/` | 33 hand-computed expectations against the same catalog + policy; `expected_output` maps onto `PricingDecision` |
| `eval/harness.py` monkeypatching, `llm_judge.py`, `langfuse_experiment.py` | Rea decides | — | not needed for the slice |
| `data/samples/scenarios.json`, `samples.py` | reuse as seed | `data/samples/requests.json` (structured, + addresses added), `data/samples/inbox/` (email texts for Jenny) | |
| `app.py` | reuse helpers only | `app/ui.py` | `_money`, line tables, secrets→env bootstrap, access-code gate; page rebuilt around queue + detail |
| `agent/extraction.py`, `test_extraction.py` | do not migrate | — | Jenny's module |
| tests: engine, policy, tools, resolution, advisor, models, db_build | port | `tests/…` | regression net for the migration; `test_pricing_agent.py` rewritten as `tests/workflow/` |

Pricing effort estimate: the port (engine/policy/types/catalog + tests) is mechanical, ~½ day; the new pricing work is `service.price_request()` producing `PricingDecision` with `rationale`/`warnings`/`policy_version`, ~½ day; `explain/` prompt rewrite + validation port, ~½ day.

---

## 6. CLAUDE.md (root of `ds-sisters-quote-workflow`)

```markdown
# DSister Quote Workflow

## Purpose
An RFQ-to-quote workflow with selective AI. An email/RFQ becomes a persisted QuoteCase,
is priced deterministically, explained by an LLM for a human reviewer, approved or
rejected in a Streamlit portal, and turned into a quotation. Course/MVP project:
clarity and a working end-to-end path beat robustness.

## MVP scope
Email/RFQ → Intake → complete QuoteRequest → Pricing → ReviewerSummary → persisted
QuoteCase → Reviewer Portal → human decision → Quotation → Evaluation.

Out of scope — do not build or leave hooks for: inventory/stock/warehouse, freight/
carrier/shipping optimisation, CRM/ERP integration, authentication, async workers/
queues, generic plugin or pipeline frameworks. Static demo fields (e.g. an estimated
lead time note on a quotation) are fine; subsystems behind them are not.

## Module ownership
| Path | Owner | Produces |
|---|---|---|
| `src/quote_workflow/contracts/` | shared — see rules below | models, enums, CaseStore |
| `intake/`, `scripts/ingest_inbox.py`, `data/samples/inbox/` | Jenny | complete `QuoteRequest` |
| `observability/`, `evaluation/`, `data/eval/`, `scripts/run_eval.py` | Rea | tracing, evaluation |
| `app/`, `quotation/` | Yinping | portal, `Quotation` |
| `catalog/`, `pricing/`, `explain/`, `storage/`, `workflow/`, `config.py` | Yinping (integration) — see docs/architecture-review.md §7 for handoffs | `PricingDecision`, `ReviewerSummary`, `CaseStore`, orchestration |
Work inside your module. Touch another module only when integration requires it, and
say so in the PR.

## Shared contracts (`contracts/`)
- Only true cross-module shapes live here: QuoteRequest/QuoteLine/Address, RfqSource,
  PricingDecision, ReviewerSummary, ReviewDecision, Quotation, QuoteCase/CaseEvent,
  CaseStatus, CaseStore. Module-internal types stay in their module.
- Pydantic v2, StrEnum, JSON round-trippable. New fields are Optional with defaults so
  stored cases keep loading. Changes are small, intentional, and announced in the PR.
- `QuoteRequest` is the normalized commercial request pricing consumes; `QuoteCase` is
  the persisted case record. Modules take typed inputs and return typed outputs; only
  `workflow/` attaches outputs to a case and persists it.
- `QuoteRequest.is_complete` / `missing_fields()` is the single definition of "enough
  to price and quote": resolved customer, ≥1 priceable line, billing + shipping address.

## Deterministic pricing
Every price, discount, margin, counter, and pricing status comes from `pricing/`
(plain Python + `config/policy.yaml`). No prompts, no network, no LLM there.
`PricingDecision` is final once produced; nothing downstream changes its numbers.
The AI never determines the final price.

## Selective AI
LLMs are used in two places: intake (reading the RFQ) and `explain/` (wording the
reviewer summary). Any LLM output that reaches a case has a structured output model, a
validation step, and a deterministic fallback. `explain/` may only use numbers present
in the facts it is given; on any failure it falls back to a summary built from
`PricingDecision.rationale`. A missing API key must never change a price or a status.

## Intake
The architecture defines what intake must produce — a `QuoteRequest` that is complete
(or a case moved to NEEDS_INFO with clarification questions) — not how. Extraction
approach, attachment/PDF handling, clarification logic, and entity resolution are the
intake owner's choices. `catalog.resolve()` and `catalog.search_*` are available
helpers, not requirements. Downstream code never asks where a field came from.

## Persistence
SQLite `data/db/cases.db`: `cases` holds current state (one row per case, JSON blob +
a few queryable columns); `case_events` is an append-only history of stage results and
status transitions. No event sourcing, no migrations — bump `schema_version`, delete
the db, reseed. `catalog.db` is separate and rebuilt by `scripts/build_db.py`.

## Reviewer workflow
Statuses: RECEIVED, NEEDS_INFO, READY_FOR_REVIEW, APPROVED, REJECTED, FAILED.
READY_FOR_REVIEW means the request is complete and a PricingDecision exists.
Transitions happen only through `workflow/` (`submit_request`, `price_and_summarize`,
`apply_review`); the portal calls those functions and never changes status itself.
Reviewer actions: Approve, Reject, Request Information. No price overrides in the MVP.
Case detail shows: request/customer info (billing, shipping, delivery date), items,
pricing result, pricing rationale, AI reviewer summary, warnings/missing information,
the three actions, and the quotation after approval.

## Quotation
Structured `Quotation` model first (quote number, case id, dates, customer, billing and
shipping addresses, delivery date, line items, subtotal/discount/total, payment terms,
notes) plus a rendered markdown body. PDF is optional, later, and only a renderer over
the model.

## Dependencies (guidance, not a framework)
Integrate through contracts; `workflow/` is the composer; keep cross-module imports
few. Feature modules should not import each other's internals; `app/` should go through
`workflow/` and `CaseStore`. Pragmatic exceptions are fine (evaluation may call
`pricing.service` directly). Do not add wrappers or abstractions to enforce purity.

## Conventions and testing
- Python 3.12, type hints, `from __future__ import annotations`, ruff defaults.
- Module docstring states what the module owns and what it must not do.
- Plain functions over classes; no base classes "for later"; no unused config options.
- `pytest` from the repo root passes before a PR; tests use temp SQLite fixtures, no
  network, no keys; LLM clients are injected and mocked.
- Pricing changes come with a hand-computed expected number. Golden cases are
  hand-computed, never copied from pipeline output.

## Running
`pip install -e ".[dev]"` (extras: `llm`, `observability`, `ui`), copy `.env.example`
→ `.env`, `python scripts/build_db.py`, `python scripts/seed_cases.py`,
`streamlit run app/streamlit_app.py`.

## Git
`main` is always runnable. Branch per module/feature (`feature/intake-…`,
`feature/eval-…`, `feature/portal-…`). Small PRs; the description names any file
touched outside your module. Claude Code: do not push, merge, or open PRs unless asked;
commit only when asked.

## Don't over-engineer
No generic pipeline/step framework, plugin registry, or abstract Agent class. No
speculative config, migrations, auth, async, or queues. No pricing math in the UI,
prompts, or workflow. No LLM output on a case without validation.
```

---

## 7. Ownership gaps and remaining team decisions

### Components without an owner today
Named owners: Jenny — intake; Rea — observability + evaluation; Yinping — quotation portal (`app/`, `quotation/`). Unowned:

| Component | Effort | Recommendation |
|---|---|---|
| Repo scaffold, `pyproject`, `config.py`, `contracts/` (initial version + stewardship) | ½ day | Yinping — it is the integration role and must land first (day 1) so Jenny and Rea can branch |
| `catalog/` (reference data + lookups + resolve helper) | ½ day, mechanical port | Yinping — pricing and intake both depend on it; ships with contracts |
| `pricing/` port + `service.price_request()` | ~1 day total | Yinping. The engine is proven (POC tests); the new work is thin (`PricingDecision`, rationale strings, policy version). Not enough to justify a fourth owner |
| `storage/` + `workflow/` | 1 day | Yinping — inseparable from the portal in the vertical slice |
| `explain/` (LLM reviewer summary) | ½–1 day | **The one hand-off candidate.** Slice runs on the deterministic fallback first; whoever frees up first (Jenny after intake, or Rea, whose evaluation needs a summary to judge) can take the prompt/validation. Default: Yinping |
| Tracing inside `workflow/` and `catalog/` | small | Rea, coordinating with Yinping since it touches workflow code — agree on where spans go before Rea edits `pipeline.py` |

Net: Yinping carries scaffold + contracts + catalog + pricing + storage + workflow + portal + quotation. Most of it is porting; the risk is the portal getting squeezed, which is why `explain/` should be the first thing handed off.

### Decisions that need team agreement before scaffolding
1. **Ownership of `explain/`** and the tracing hand-off above.
2. **LLM provider/model for both call sites.** The POC uses OpenAI structured outputs (`chat.completions.parse` via `langfuse.openai`). Keeping it lets `explain/` validation port verbatim; Jenny's intake should use the same provider so keys, tracing and mocking are uniform. Decide once.
3. **Langfuse as a hard vs optional dependency.** POC imports it at module top in tools/orchestrator. Rea's call; recommend optional (extras) so tests and teammates without keys run everything.
4. **Address requiredness.** Plan says billing + shipping are required for `READY_FOR_REVIEW`. If sample emails often lack them, Jenny needs a customer-master fallback in intake (the catalog `customers` table has no address columns today — add `billing_address`/`shipping_address` columns to `data/reference/customers.csv` so intake can default from master data?). Recommend adding them to the reference data.
5. **Catalog data stays the POC's** (WWI toys/mugs, ~12 customers/products, hand-authored deals) — the 33 golden expectations depend on it. Confirm; if the team wants "pumps" for the demo, it costs recomputing goldens.
6. **Default reviewer / assignment.** One default name, "view as" in the UI. Confirm no routing logic.
7. **Quote number format and `valid_until` rule** (e.g. `Q-<yyyy>-<seq>`, 30 days). Trivial but shared.

## Next step after approval
1. `git init` on `main`; scaffold the tree in §1; write CLAUDE.md (§6), pyproject, `.env.example`, README.
2. Port contracts + catalog + pricing with their tests (regression net).
3. Build the slice: `seed_cases.py` → `submit_request` → `price_and_summarize` (fallback summary) → storage → Streamlit queue → case detail → `apply_review` → `Quotation`.
4. Push so Jenny and Rea branch from a contracts-bearing `main`; then `explain/` LLM path and Technical Trace.
The POC is never modified.
