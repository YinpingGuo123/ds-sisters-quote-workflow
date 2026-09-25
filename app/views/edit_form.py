"""The reviewer's correction dialog: fix what intake got wrong or never found.

Presentation only. The form builds a corrected ``QuoteRequest`` and hands it to
``workflow.apply_edit``, which records the edit and re-runs the standard seam -
so whether the case ends in NEEDS_INFO or is re-priced is decided by the
contract's completeness rule, never here.

Prices are deliberately not editable: no price overrides in the MVP.
"""

from __future__ import annotations

import sqlite3

import streamlit as st

from quote_workflow.contracts.case import QuoteCase
from quote_workflow.contracts.common import Address
from quote_workflow.contracts.quote_request import QuoteRequest
from quote_workflow.contracts.store import CaseStore
from quote_workflow.workflow import apply_edit


def _address_inputs(label: str, address: Address | None, prefix: str) -> Address | None:
    """Inputs for one address. Returns None while a required part is still blank,
    which is how the completeness rule keeps seeing it as missing."""
    st.markdown(f"**{label}**")
    if address is None:
        st.caption("Not provided yet.")
    name = st.text_input("Name / company", value=(address.name or "") if address else "", key=f"{prefix}-name")
    line1 = st.text_input("Address line 1", value=address.line1 if address else "", key=f"{prefix}-line1")
    line2 = st.text_input("Address line 2", value=(address.line2 or "") if address else "", key=f"{prefix}-line2")
    city = st.text_input("City", value=address.city if address else "", key=f"{prefix}-city")
    cols = st.columns(2)
    region = cols[0].text_input(
        "State / region", value=(address.region or "") if address else "", key=f"{prefix}-region"
    )
    postal = cols[1].text_input(
        "Postal code", value=(address.postal_code or "") if address else "", key=f"{prefix}-postal"
    )
    country = st.text_input("Country", value=address.country if address else "", key=f"{prefix}-country")

    if not (line1.strip() and city.strip() and country.strip()):
        return None
    return Address(
        name=name.strip() or None,
        line1=line1.strip(),
        line2=line2.strip() or None,
        city=city.strip(),
        region=region.strip() or None,
        postal_code=postal.strip() or None,
        country=country.strip(),
    )


def _edited_request(request: QuoteRequest, case_id: str) -> QuoteRequest:
    """Every editable field, rendered and collected into a corrected request."""
    billing_col, shipping_col = st.columns(2)
    with billing_col:
        billing = _address_inputs("Billing address", request.billing_address, f"{case_id}-bill")
    with shipping_col:
        shipping = _address_inputs("Shipping address", request.shipping_address, f"{case_id}-ship")

    st.markdown("**Terms**")
    cols = st.columns(2)
    delivery = cols[0].date_input(
        "Requested delivery date", value=request.requested_delivery_date, key=f"{case_id}-delivery"
    )
    months = cols[1].number_input(
        "Contract term (months)",
        min_value=0,
        step=1,
        value=int(request.contract_months or 0),
        key=f"{case_id}-months",
    )

    lines = []
    if request.lines:
        st.markdown("**Quantities**")
        for number, line in enumerate(request.lines, start=1):
            quantity = st.number_input(
                f"Line {number}: {line.product_name or 'unidentified product'}",
                min_value=0,
                step=1,
                value=int(line.quantity or 0),
                help="0 leaves the quantity unknown, which keeps the case in Needs Info.",
                key=f"{case_id}-qty-{number}",
            )
            lines.append(line.model_copy(update={"quantity": int(quantity) or None}))

    return request.model_copy(
        update={
            "billing_address": billing,
            "shipping_address": shipping,
            "requested_delivery_date": delivery,
            "contract_months": int(months) or None,
            "lines": lines,
        }
    )


# Which case's dialog is open. A dialog only exists while the app calls its
# function, so the open/closed state has to live somewhere the next run can see
# it - otherwise a full rerun (rather than a dialog-scoped one) drops the form
# before its submit is handled.
OPEN_EDIT_CASE = "edit_dialog_case_id"


def _close_edit() -> None:
    st.session_state[OPEN_EDIT_CASE] = None


def request_edit(case_id: str) -> None:
    """Open the edit dialog for this case on this and following runs."""
    st.session_state[OPEN_EDIT_CASE] = case_id


def render_edit_dialog(case: QuoteCase, store: CaseStore, conn: sqlite3.Connection, viewer: str) -> None:
    """Render the dialog while it is open for this case."""
    if st.session_state.get(OPEN_EDIT_CASE) == case.case_id:
        edit_dialog(case, store, conn, viewer)


@st.dialog("Edit case information", width="large", on_dismiss=_close_edit)
def edit_dialog(case: QuoteCase, store: CaseStore, conn: sqlite3.Connection, viewer: str) -> None:
    """Correct a case, then let the workflow decide where it lands."""
    if case.request is None:
        st.info("There is no request on this case yet - intake has not produced one.")
        return

    st.caption(
        f"Saving re-runs pricing for {case.case_id}. "
        "Anything still missing keeps the case in Needs Info; prices cannot be edited."
    )
    with st.form(f"edit-{case.case_id}"):
        edited = _edited_request(case.request, case.case_id)
        note = st.text_input("Note for the case history (optional)", key=f"{case.case_id}-edit-note")
        saved = st.form_submit_button("Save changes", type="primary")

    if not saved:
        return
    try:
        apply_edit(
            store,
            conn,
            case.case_id,
            edited,
            editor=viewer,
            note=note.strip() or None,
            use_llm=st.session_state.get("use_llm", False),
        )
    except ValueError as exc:  # a case decided in another tab, a request that cannot be re-run
        st.error(str(exc))
        return
    _close_edit()
    st.rerun()
