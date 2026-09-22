# DSister Quote Workflow

## Purpose
An RFQ-to-quote workflow with selective AI. An email/RFQ becomes a persisted QuoteCase,
is priced deterministically, explained by an LLM for a human reviewer, approved or
rejected in a Streamlit portal, and turned into a quotation. Course/MVP project:
clarity and a working end-to-end path beat robustness.

Full design: `docs/architecture-review.md`.

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
| `catalog/`, `pricing/`, `explain/`, `storage/`, `workflow/`, `config.py` | Yinping (integration) — `explain/` is the first hand-off candidate | `PricingDecision`, `ReviewerSummary`, `CaseStore`, orchestration |

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
Hand the result to `workflow.submit_request(store, conn, case_id, request)`.

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
```
python -m venv .venv && .venv\Scripts\Activate.ps1
pip install -e ".[dev,llm,observability,ui]"
copy .env.example .env
python scripts/build_db.py
python scripts/seed_cases.py
python scripts/run_case.py --all
.venv\Scripts\python.exe -m streamlit run app/streamlit_app.py
```

## Git
`main` is always runnable. Branch per module/feature (`feature/intake-…`,
`feature/eval-…`, `feature/portal-…`). Small PRs; the description names any file
touched outside your module. Claude Code: do not push, merge, or open PRs unless asked;
commit only when asked.

## Don't over-engineer
No generic pipeline/step framework, plugin registry, or abstract Agent class. No
speculative config, migrations, auth, async, or queues. No pricing math in the UI,
prompts, or workflow. No LLM output on a case without validation.
