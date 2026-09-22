"""Business View of one case: request, items, pricing result, pricing
rationale, AI reviewer summary, warnings, actions, quotation.

Every number shown is read from the persisted case. Actions call
``workflow.apply_review``; this file never changes a status itself.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pandas as pd
import streamlit as st

from quote_workflow.contracts.case import QuoteCase
from quote_workflow.contracts.enums import CaseStatus, ReviewAction
from quote_workflow.contracts.review import ReviewDecision
from quote_workflow.contracts.store import CaseStore
from quote_workflow.workflow import apply_review, rerun
from ui import money, pct, pricing_badge, status_badge


def _header(case: QuoteCase) -> None:
    left, right = st.columns([3, 1])
    with left:
        st.markdown(f"## {case.case_id} &nbsp;|&nbsp; {case.customer_display}")
        cols = st.columns([1, 1, 3])
        with cols[0]:
            status_badge(case.status)
        with cols[1]:
            if case.pricing:
                pricing_badge(case.pricing.status)
        with cols[2]:
            st.caption(f"Assigned to **{case.assigned_to or '-'}** · created {case.created_at:%b %d, %H:%M}")
    with right:
        if case.pricing:
            st.metric(
                "Quoted total",
                money(case.pricing.total_quoted_value),
                f"{-case.pricing.total_discount_pct:.1f}% vs list",
            )


def _request_section(case: QuoteCase) -> None:
    request = case.request
    st.markdown("#### Request / customer information")
    if request is None:
        st.info("No request yet - intake has not produced one for this case.")
        return
    cols = st.columns(3)
    with cols[0]:
        st.markdown("**Billing address**")
        st.text(request.billing_address.as_text() if request.billing_address else "- missing -")
    with cols[1]:
        st.markdown("**Shipping address**")
        st.text(request.shipping_address.as_text() if request.shipping_address else "- missing -")
    with cols[2]:
        st.markdown("**Terms**")
        delivery = request.requested_delivery_date.isoformat() if request.requested_delivery_date else "-"
        discount = pct(request.requested_discount_pct) if request.requested_discount_pct is not None else "-"
        st.text(
            f"Requested delivery: {delivery}\n"
            f"Contract term: {request.contract_months or 0} months\n"
            f"Requested discount: {discount}"
        )
    if request.notes:
        st.caption(f"Notes: {request.notes}")

    st.markdown("#### Items / quantities")
    rows = [
        {
            "#": n,
            "Product": line.product_name or "-",
            "Resolution": line.product_status.value + (f" ({', '.join(line.candidates)})" if line.candidates else ""),
            "Qty": line.quantity if line.quantity is not None else "-",
            "Requested price": money(line.requested_unit_price) if line.requested_unit_price else "-",
            "Competitor price": money(line.competitor_price) if line.competitor_price else "-",
        }
        for n, line in enumerate(request.lines, start=1)
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _original_rfq(case: QuoteCase) -> None:
    source = case.source
    text = source.body_text if source else (case.request.source_text if case.request else None)
    if not text:
        return
    with st.expander("Original RFQ", expanded=False):
        if source:
            st.caption(
                f"From: {source.sender or '-'} · Subject: {source.subject or '-'} · "
                f"Received: {source.received_at:%b %d, %H:%M}"
            )
            if source.attachment_names:
                st.caption("Attachments: " + ", ".join(source.attachment_names))
        st.text(text)


def _pricing_section(case: QuoteCase) -> None:
    pricing = case.pricing
    st.markdown("#### Pricing result")
    if pricing is None:
        st.info("Not priced yet.")
        return
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
    st.caption(
        f"Priced {pricing.priced_at:%b %d, %H:%M} as of {pricing.as_of_date.isoformat()} "
        f"· policy {pricing.policy_version}"
    )

    st.markdown("#### Pricing rationale")
    for line in pricing.lines:
        with st.expander(
            f"Line {line.line_number}: {line.product_name} - {money(line.final_unit_price)} ({line.status.value})",
            expanded=len(pricing.lines) == 1,
        ):
            for sentence in line.rationale:
                st.markdown(f"- {sentence}")
            if line.historical_reference:
                st.caption(f"History: {line.historical_reference}")
            if line.levers:
                st.caption(
                    "Alternatives: "
                    + "; ".join(f"{lever.description} -> {money(lever.unit_price)}" for lever in line.levers)
                )


def _summary_section(case: QuoteCase) -> None:
    summary = case.summary
    st.markdown("#### AI reviewer summary")
    if summary is None:
        st.info("No summary yet.")
        return
    if summary.generated_by == "llm":
        st.caption(f"Generated by {summary.model}")
    else:
        st.caption(
            "Deterministic fallback"
            + (f" - LLM output rejected: {summary.rejected_reason}" if summary.rejected_reason else " (LLM not used)")
        )
    st.write(summary.summary)
    cols = st.columns(2)
    with cols[0]:
        if summary.rationale:
            st.markdown("**Rationale**")
            for item in summary.rationale:
                st.markdown(f"- {item}")
    with cols[1]:
        if summary.attention_items:
            st.markdown("**Needs your attention**")
            for item in summary.attention_items:
                st.markdown(f"- {item}")
    if summary.draft_reply:
        with st.expander("Draft reply to customer"):
            st.text(summary.draft_reply)


def _warnings_section(case: QuoteCase) -> None:
    st.markdown("#### Warnings / missing information")
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


def _actions(case: QuoteCase, store: CaseStore, conn: sqlite3.Connection, viewer: str) -> None:
    st.markdown("#### Decision")
    if case.status == CaseStatus.READY_FOR_REVIEW:
        comment = st.text_input(
            "Comment (optional; goes on the quotation notes when approving)", key=f"comment-{case.case_id}"
        )
        cols = st.columns(3)
        clicked = None
        if cols[0].button("Approve", type="primary", key=f"approve-{case.case_id}", width="stretch"):
            clicked = ReviewAction.APPROVE
        if cols[1].button("Reject", key=f"reject-{case.case_id}", width="stretch"):
            clicked = ReviewAction.REJECT
        if cols[2].button("Request information", key=f"info-{case.case_id}", width="stretch"):
            clicked = ReviewAction.REQUEST_INFO
        if clicked is not None:
            decision = ReviewDecision(
                action=clicked, reviewer=viewer, comment=comment or None, decided_at=datetime.now(UTC)
            )
            apply_review(store, case.case_id, decision)
            st.rerun()
    elif case.status == CaseStatus.FAILED:
        if st.button("Re-run pipeline", key=f"rerun-{case.case_id}"):
            rerun(store, conn, case.case_id, use_llm=st.session_state.get("use_llm", False))
            st.rerun()
    elif case.review:
        st.caption(
            f"{case.review.action.value.replace('_', ' ').title()} by {case.review.reviewer} "
            f"on {case.review.decided_at:%b %d, %H:%M}" + (f" - {case.review.comment}" if case.review.comment else "")
        )
    else:
        st.caption("Waiting for information before this case can be reviewed.")


def _quotation_section(case: QuoteCase) -> None:
    quotation = case.quotation
    if quotation is None:
        return
    st.markdown("#### Quotation")
    st.download_button(
        "Download quotation (markdown)",
        data=quotation.body_markdown,
        file_name=f"{quotation.quote_number}.md",
        mime="text/markdown",
        key=f"download-{case.case_id}",
    )
    st.markdown(quotation.body_markdown)


def render_case(case: QuoteCase, store: CaseStore, conn: sqlite3.Connection, viewer: str) -> None:
    _header(case)
    _original_rfq(case)
    _request_section(case)
    _pricing_section(case)
    _summary_section(case)
    _warnings_section(case)
    _actions(case, store, conn, viewer)
    _quotation_section(case)
