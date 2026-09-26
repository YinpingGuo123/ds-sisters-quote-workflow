"""Business View of one case, as a card grid with a timeline rail.

Every number shown is read from the persisted case. Actions call ``workflow``;
this file never changes a status itself.

Note the two separate cards for pricing and for the AI summary. Pricing is
deterministic - policy plus plain Python - so its card is titled "Pricing
Recommendation" and its bullets come from ``PricingDecision.rationale``. The
only LLM-authored content on a case is ``ReviewerSummary``, which has its own
card and its own llm/fallback badge. Labelling a price as AI-produced would
misrepresent how it was decided.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pandas as pd
import streamlit as st
from resources import use_llm

from quote_workflow.contracts.case import QuoteCase
from quote_workflow.contracts.enums import CaseStatus, QuotationFormat, ReviewAction
from quote_workflow.contracts.quotation import Quotation
from quote_workflow.contracts.review import ReviewDecision
from quote_workflow.contracts.store import CaseStore
from quote_workflow.quotation import build_quotation, renderer_for
from quote_workflow.workflow import apply_review, rerun, run_rework
from ui import money, pct, pricing_badge, status_badge
from views.edit_form import render_edit_dialog, request_edit
from views.reject_form import render_reject_dialog, request_reject
from views.rework_form import render_revise_dialog, request_revise
from views.timeline import render_timeline


def _header(case: QuoteCase) -> None:
    left, right = st.columns([3, 1])
    with left:
        st.markdown(f"## {case.case_id} &nbsp;|&nbsp; {case.customer_display}")
        status_badge(case.status)
        st.caption(f"Assigned to **{case.assigned_to or '-'}** · created {case.created_at:%b %d, %H:%M}")
    with right:
        if case.pricing:
            st.metric(
                "Quoted total",
                money(case.pricing.total_quoted_value),
                f"{-case.pricing.total_discount_pct:.1f}% vs list",
            )


# --- cards ---------------------------------------------------------------------


def _rfq_card(case: QuoteCase) -> None:
    with st.container(border=True):
        st.markdown("###### :material/mail: Original RFQ")
        source = case.source
        text = source.body_text if source else (case.request.source_text if case.request else None)
        if source:
            st.caption(
                f"From: {source.sender or '-'}  \nSubject: {source.subject or '-'}  \n"
                f"Received: {source.received_at:%b %d, %H:%M}"
            )
        if not text:
            st.caption("No original message - this case was created from a structured request.")
            return
        st.text(text if len(text) < 400 else text[:400] + " ...")
        if source and source.attachment_names:
            st.caption(":material/attach_file: " + " · ".join(source.attachment_names))


def _extracted_card(case: QuoteCase) -> None:
    with st.container(border=True):
        st.markdown("###### :material/description: Extracted Data")
        request = case.request
        if request is None:
            st.caption("No request yet - intake has not produced one for this case.")
            return
        delivery = request.requested_delivery_date.isoformat() if request.requested_delivery_date else "-"
        st.markdown(
            f"**Customer** · {request.customer_name or '-'}  \n"
            f"**Delivery date** · {delivery}  \n"
            f"**Contract term** · {request.contract_months or 0} months"
        )
        for number, line in enumerate(request.lines, start=1):
            quantity = f"{line.quantity:,}" if line.quantity is not None else "?"
            st.markdown(f"**Line {number}** · {line.product_name or '-'} — {quantity} units")
            if line.product_status.value != "resolved":
                st.caption(f"resolution: {line.product_status.value}")
        st.markdown("**Bill to**")
        st.caption(request.billing_address.as_text() if request.billing_address else "- missing -")
        st.markdown("**Ship to**")
        st.caption(request.shipping_address.as_text() if request.shipping_address else "- missing -")


def _pricing_card(case: QuoteCase) -> None:
    with st.container(border=True):
        st.markdown("###### :material/insights: Pricing Recommendation")
        pricing = case.pricing
        if pricing is None:
            st.caption("Not priced yet.")
            return
        st.metric("Quoted total", money(pricing.total_quoted_value), f"{-pricing.total_discount_pct:.1f}% vs list")
        pricing_badge(pricing.status)
        st.caption(f"Blended margin {pct(pricing.blended_margin_pct)}")

        st.markdown("**Rationale**")
        for line in pricing.lines:
            if len(pricing.lines) > 1:
                st.caption(f"Line {line.line_number}: {line.product_name}")
            for sentence in line.rationale:
                st.markdown(f"- {sentence}")
        st.caption(
            f"Deterministic - policy {pricing.policy_version}, as of {pricing.as_of_date.isoformat()}. "
            "Computed from pricing rules, not by the AI."
        )


def _summary_card(case: QuoteCase) -> None:
    with st.container(border=True):
        st.markdown("###### :material/auto_awesome: AI Reviewer Summary")
        summary = case.summary
        if summary is None:
            st.caption("No summary yet.")
            return
        if summary.generated_by == "llm":
            st.caption(f"Generated by {summary.model}")
        else:
            why = f" - LLM output rejected: {summary.rejected_reason}" if summary.rejected_reason else " (LLM not used)"
            st.caption("Deterministic fallback" + why)
        st.write(summary.summary)
        if summary.rationale:
            st.markdown("**Rationale**")
            for item in summary.rationale:
                st.markdown(f"- {item}")
        if summary.attention_items:
            st.markdown("**Needs your attention**")
            for item in summary.attention_items:
                st.markdown(f"- {item}")
        if summary.draft_reply:
            with st.expander("Draft reply to customer"):
                st.text(summary.draft_reply)


def _warnings_card(case: QuoteCase) -> None:
    with st.container(border=True):
        st.markdown("###### :material/warning: Validation & Warnings")
        shown = False
        if case.request:
            for item in case.request.missing_fields():
                st.warning(item)
                shown = True
            for question in case.request.clarification_questions:
                st.info(f"Clarification: {question}")
                shown = True
        if case.pricing:
            for item in case.pricing.warnings:
                st.warning(item)
                shown = True
        if case.summary and case.summary.generated_by == "llm":
            for item in case.summary.warnings:
                st.warning(f"AI: {item}")
                shown = True
        if not shown:
            st.success("Nothing flagged.")


# --- full-width sections -------------------------------------------------------


def _pricing_detail(case: QuoteCase) -> None:
    pricing = case.pricing
    if pricing is None:
        return
    with st.expander("Pricing detail - per line", expanded=False):
        rows = [
            {
                "#": line.line_number,
                "Product": line.product_name,
                "Qty": line.quantity,
                "List": money(line.list_price),
                "Deal / ladders": line.applicable_deal
                or (
                    f"vol {line.volume_discount_pct:g}% · term {line.term_discount_pct:g}%"
                    if line.volume_discount_pct or line.term_discount_pct
                    else "-"
                ),
                "Recommended": money(line.recommended_unit_price),
                "Requested": money(line.requested_unit_price) if line.requested_unit_price else "-",
                "Counter": money(line.counter_unit_price) if line.counter_unit_price else "-",
                "Final": money(line.final_unit_price),
                "Line total": money(line.line_total),
                "Margin": pct(line.margin_pct),
                "Status": line.status.value,
            }
            for line in pricing.lines
        ]
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        cols = st.columns(4)
        cols[0].metric("List value", money(pricing.total_list_value))
        cols[1].metric("Quoted", money(pricing.total_quoted_value))
        cols[2].metric("Discount", pct(pricing.total_discount_pct))
        cols[3].metric("Blended margin", pct(pricing.blended_margin_pct))
        for line in pricing.lines:
            if line.historical_reference:
                st.caption(f"Line {line.line_number} history: {line.historical_reference}")
            if line.levers:
                st.caption(
                    f"Line {line.line_number} alternatives: "
                    + "; ".join(f"{lever.description} -> {money(lever.unit_price)}" for lever in line.levers)
                )


def _document_body(quotation: Quotation) -> None:
    """Show a rendered quotation inline when the format allows it."""
    if quotation.body_format is QuotationFormat.MARKDOWN:
        st.markdown(quotation.body)
    else:
        st.caption(f"{quotation.body_format.value.upper()} document - download it to view.")


def _quotation_section(case: QuoteCase) -> None:
    """The approved quotation, or a draft preview of what approving would produce."""
    with st.container(border=True):
        if case.quotation is not None:
            quotation, label, key = case.quotation, "Quotation", "quotation"
            st.markdown("###### :material/receipt_long: Quotation")
            st.caption(f"{quotation.quote_number} · generated {quotation.generated_at:%b %d, %H:%M}")
        else:
            st.markdown("###### :material/draft: Draft Quote")
            try:
                quotation = build_quotation(case)
            except ValueError as exc:  # not priced, or addresses still missing
                st.caption(f"No draft yet - {exc}.")
                return
            label, key = "Draft", "draft"
            st.caption("Preview only. The quotation is created and stored when the case is approved.")

        renderer = renderer_for(quotation.body_format)
        st.download_button(
            f"Download {label.lower()} ({renderer.extension})",
            data=quotation.body,
            file_name=renderer.filename(quotation),
            mime=renderer.media_type,
            key=f"download-{key}-{case.case_id}",
        )
        with st.expander("Preview document", expanded=False):
            _document_body(quotation)


# --- actions -------------------------------------------------------------------


def _last_decision(case: QuoteCase) -> None:
    review = case.review
    if not review:
        return
    text = f"{review.action.value.replace('_', ' ').title()} by {review.reviewer} on {review.decided_at:%b %d, %H:%M}"
    if review.rejection_reason:
        text += f" · reason: {review.rejection_reason.value.replace('_', ' ')}"
    st.caption(text + (f" - {review.comment}" if review.comment else ""))


def _actions(case: QuoteCase, store: CaseStore, conn: sqlite3.Connection, viewer: str) -> None:
    st.markdown("#### Decision")
    if case.status == CaseStatus.READY_FOR_REVIEW:
        comment = st.text_input(
            "Comment (optional; goes on the quotation notes when approving)", key=f"comment-{case.case_id}"
        )
        cols = st.columns(4)
        clicked = None
        if cols[0].button("Approve", type="primary", key=f"approve-{case.case_id}", width="stretch"):
            clicked = ReviewAction.APPROVE
        if cols[1].button("Edit", key=f"edit-{case.case_id}", width="stretch"):
            request_edit(case.case_id)
        if cols[2].button("Send back", key=f"revise-{case.case_id}", width="stretch"):
            request_revise(case.case_id)
        if cols[3].button("Reject", key=f"reject-{case.case_id}", width="stretch"):
            request_reject(case.case_id)  # the reason is required, so it is asked for in a dialog
        if clicked is not None:
            decision = ReviewDecision(
                action=clicked, reviewer=viewer, comment=comment or None, decided_at=datetime.now(UTC)
            )
            apply_review(store, case.case_id, decision)
            st.rerun()
    elif case.status == CaseStatus.REWORK_REQUESTED:
        rework = case.rework
        st.warning(
            f"**{rework.target.value.title()} rework requested** by {rework.requested_by} "
            f"on {rework.requested_at:%b %d, %H:%M}\n\n{rework.reason}"
            if rework
            else "Rework requested."
        )
        st.caption(
            "The case cannot be approved until this is done. Run it here, or let "
            "scripts/run_rework.py pick it up."
        )
        if st.button("Run rework now", type="primary", key=f"run-rework-{case.case_id}"):
            run_rework(store, conn, case.case_id, use_llm=use_llm())
            st.rerun()
    elif case.status == CaseStatus.NEEDS_INFO:
        _last_decision(case)
        st.caption("This case is waiting for information. Supply it here and pricing re-runs automatically.")
        if st.button("Edit case information", type="primary", key=f"edit-{case.case_id}"):
            request_edit(case.case_id)
    elif case.status == CaseStatus.FAILED:
        if st.button("Re-run pipeline", key=f"rerun-{case.case_id}"):
            rerun(store, conn, case.case_id, use_llm=use_llm())
            st.rerun()
    elif case.review:
        _last_decision(case)
    else:
        st.caption("Waiting for information before this case can be reviewed.")

    render_edit_dialog(case, store, conn, viewer)
    render_revise_dialog(case, store, viewer)
    render_reject_dialog(case, store, viewer)


def render_case(case: QuoteCase, store: CaseStore, conn: sqlite3.Connection, viewer: str) -> None:
    _header(case)
    content, rail = st.columns([3, 1])
    with content:
        top = st.columns(3)
        with top[0]:
            _rfq_card(case)
        with top[1]:
            _extracted_card(case)
        with top[2]:
            _pricing_card(case)
        bottom = st.columns(2)
        with bottom[0]:
            _summary_card(case)
        with bottom[1]:
            _warnings_card(case)
        _pricing_detail(case)
        _quotation_section(case)
        _actions(case, store, conn, viewer)
    with rail:
        render_timeline(case)
