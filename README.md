# DSister Quote Workflow

An RFQ-to-quote workflow with selective AI. An email/RFQ becomes a persisted
**QuoteCase**, is priced **deterministically**, explained by an LLM for a human
**reviewer**, approved or rejected in a **Streamlit portal**, and turned into a
**quotation**.

```
Email / RFQ → Intake → complete QuoteRequest → Pricing → ReviewerSummary
→ persisted QuoteCase → Reviewer Portal → Human decision → Quotation → Evaluation
```

Design, contracts, ownership and scope: [`docs/architecture-review.md`](docs/architecture-review.md).
Rules for working in this repo (also read by Claude Code): [`CLAUDE.md`](CLAUDE.md).

## Setup

```powershell
python -m venv .venv            # Python 3.12
.venv\Scripts\Activate.ps1
pip install -e ".[dev,llm,observability,ui]"
copy .env.example .env          # optional: OPENAI_API_KEY for the AI reviewer summary
```

Everything deterministic runs with no keys at all; without `OPENAI_API_KEY` the
reviewer summary is the code-built fallback and prices/statuses are identical.

## Run

```powershell
python scripts/build_db.py          # data/reference/*.csv -> data/db/catalog.db
python scripts/seed_cases.py        # data/samples/requests.json -> data/db/cases.db (8 demo cases)
python scripts/run_case.py --all    # list cases; `run_case.py Q-below-floor` shows one in detail
python scripts/run_rework.py        # cases a reviewer sent back; `--run` carries the rework out
.venv\Scripts\python.exe -m streamlit run app/streamlit_app.py
```

The portal seeds the demo cases itself when the store is empty. Navigate with My
Queue / All Cases / Needs Attention / Completed, pick a case, read the extracted
data, the deterministic pricing recommendation, the AI reviewer summary and the
warnings, then Approve, Edit, Reject or Request information. Editing a case
re-runs pricing; approving stores the quotation. A draft quote is previewable
before any decision.

## Test

```powershell
pytest            # ~400 tests: ported pricing engine + catalog, and the new storage/workflow/explain/quotation/portal
ruff check .      # lint (rules pinned in pyproject.toml)
```

## Layout

```
config/policy.yaml            pricing rules (margin floors, ladders, per-segment caps) + version
data/reference/               catalog seed CSVs (customers, products, aliases, deals, sales history)
data/samples/requests.json    structured sample requests used to seed demo cases
data/samples/inbox/           sample RFQ emails for intake
data/eval/                    golden cases (evaluation)
src/quote_workflow/
  contracts/                  SHARED models: QuoteRequest, PricingDecision, ReviewerSummary, ReviewDecision,
                              Quotation, QuoteCase/CaseEvent, CaseStatus, CaseStore
  catalog/                    reference data: SQLite build, lookups, deterministic resolve() helper
  intake/                     RfqSource -> complete QuoteRequest             (owner: Jenny)
  pricing/                    deterministic engine + policy; service.price_request() -> PricingDecision
  explain/                    LLM reviewer summary, grounded + validated, with fallback
  quotation/                  build_quotation() -> Quotation; renderers/ markdown today, HTML/PDF by adding one entry
  storage/                    SqliteCaseStore: `cases` (current state) + `case_events` (history)
  workflow/                   the composer: submit_request / price_and_summarize / apply_review
  observability/              tracing setup                                   (owner: Rea)
  evaluation/                 evaluation                                      (owner: Rea)
app/                          Streamlit portal: left navigation (screens/), queue, case detail
                              cards, processing timeline, technical trace
scripts/                      build_db, seed_cases, run_case, run_rework
                              (+ ingest_inbox, run_eval by their owners)
tests/                        pytest; temp SQLite fixtures, no network, LLM clients mocked
```

## Integration points

- **Intake** hands its result to `workflow.submit_request(store, conn, case_id, request)`.
  A `QuoteRequest` is complete when `request.is_complete` (resolved customer, ≥1
  priceable line, billing + shipping address); otherwise the case goes to `NEEDS_INFO`
  with `request.missing_fields()` and `clarification_questions` in the event log.
  Start a case with `workflow.create_case(store, source=RfqSource(...))`.
- **Evaluation** can drive the same path with `workflow.create_case_from_request(...)`
  or call `pricing.service.price_request(conn, request)` directly, and read cases
  back through `SqliteCaseStore.list()/get()`.
- **Observability** hooks go in `workflow/pipeline.py` (stage spans) and
  `explain/summarize.py` (the LLM call); `observability/tracing.py` has the Langfuse
  bootstrap carried over from the POC.

## Data

The catalog (customer and product names, list prices) is derived from Microsoft's
WideWorldImporters sample; tiers, costs, aliases, deals and sales history are
hand-authored to exercise specific pricing scenarios. Addresses in the sample
requests are fictional. See the POC's README for provenance details.
