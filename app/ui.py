"""Formatting helpers for the portal. Presentation only - no domain logic."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from quote_workflow.contracts.enums import CaseStatus, PricingStatus

STATUS_LABEL = {
    CaseStatus.RECEIVED: "Received",
    CaseStatus.NEEDS_INFO: "Needs Info",
    CaseStatus.READY_FOR_REVIEW: "Ready for Review",
    CaseStatus.REWORK_REQUESTED: "Rework Requested",
    CaseStatus.APPROVED: "Approved",
    CaseStatus.REJECTED: "Rejected",
    CaseStatus.FAILED: "Failed",
}

STATUS_COLOR = {
    CaseStatus.RECEIVED: "gray",
    CaseStatus.NEEDS_INFO: "orange",
    CaseStatus.READY_FOR_REVIEW: "blue",
    CaseStatus.REWORK_REQUESTED: "gray",  # in progress elsewhere, not the reviewer's move
    CaseStatus.APPROVED: "green",
    CaseStatus.REJECTED: "red",
    CaseStatus.FAILED: "red",
}

PRICING_LABEL = {
    PricingStatus.APPROVED: "within policy",
    PricingStatus.COUNTER_RECOMMENDED: "counter recommended",
    PricingStatus.ESCALATION_REQUIRED: "escalation required",
    PricingStatus.INSUFFICIENT_DATA: "insufficient data",
}

PRICING_COLOR = {
    PricingStatus.APPROVED: "green",
    PricingStatus.COUNTER_RECOMMENDED: "orange",
    PricingStatus.ESCALATION_REQUIRED: "orange",
    PricingStatus.INSUFFICIENT_DATA: "red",
}


def money(value: float | None) -> str:
    return "-" if value is None else f"${value:,.2f}"


def pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}%"


def when(value: datetime) -> str:
    return value.astimezone().strftime("%b %d, %H:%M")


def status_badge(status: CaseStatus) -> None:
    st.badge(STATUS_LABEL[status], color=STATUS_COLOR[status])


def pricing_badge(status: PricingStatus) -> None:
    st.badge(PRICING_LABEL[status], color=PRICING_COLOR[status])
