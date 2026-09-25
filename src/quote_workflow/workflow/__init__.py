"""Orchestration: the only module that composes intake, catalog, pricing,
explain, quotation and storage.

Entry points:
- ``create_case(store, source)``                       a RECEIVED case (intake's starting point)
- ``submit_request(store, conn, case_id, request)``   THE seam: attach a request; NEEDS_INFO or price
- ``create_case_from_request(...)``                    create + submit in one call (seeding, tests, evaluation)
- ``price_and_summarize(store, conn, case_id)``       pricing -> reviewer summary -> READY_FOR_REVIEW
- ``apply_review(store, case_id, decision)``          approve (builds the quotation) / reject / request info
- ``apply_edit(store, conn, case_id, request, editor)`` reviewer correction -> submit_request -> re-priced
- ``rerun(store, conn, case_id)``                     re-run a FAILED case from its stored request
"""

from quote_workflow.workflow.pipeline import (
    create_case,
    create_case_from_request,
    new_case_id,
    price_and_summarize,
    rerun,
    submit_request,
)
from quote_workflow.workflow.review import apply_edit, apply_review
from quote_workflow.workflow.status import InvalidTransition, check_transition, is_terminal

__all__ = [
    "InvalidTransition",
    "apply_edit",
    "apply_review",
    "check_transition",
    "create_case",
    "create_case_from_request",
    "is_terminal",
    "new_case_id",
    "price_and_summarize",
    "rerun",
    "submit_request",
]
