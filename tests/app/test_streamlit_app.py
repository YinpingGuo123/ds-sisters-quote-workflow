"""Smoke-test the portal with Streamlit's headless AppTest: the page renders
without exceptions, the queue lists the seeded cases, and Approve on a
selected case produces a quotation. Uses temp catalog/case databases."""

from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import quote_workflow.config as config

APP = Path(__file__).resolve().parents[2] / "app" / "streamlit_app.py"


@pytest.fixture
def app(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "CATALOG_DB_PATH", tmp_path / "catalog.db")
    monkeypatch.setattr(config, "CASES_DB_PATH", tmp_path / "cases.db")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ACCESS_CODE", raising=False)
    st.cache_resource.clear()  # the app caches the store/connection across runs
    yield AppTest.from_file(str(APP), default_timeout=60)
    st.cache_resource.clear()


def _markdown_text(app: AppTest) -> str:
    return " ".join(m.value for m in app.markdown)


def test_portal_renders_queue_without_exceptions(app):
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    assert app.sidebar.selectbox[0].value == "Sarah"
    assert app.sidebar.radio[0].value == "My Queue"
    frame = app.dataframe[0].value
    assert len(frame) == 8  # every seeded sample is open (nothing approved/rejected yet)
    assert "Q-standard-quote" in set(frame["Case"])


def test_needs_info_view_lists_the_two_incomplete_samples(app):
    app.run()
    app.sidebar.radio[0].set_value("Needs Info").run()
    assert not app.exception, [e.value for e in app.exception]
    assert set(app.dataframe[0].value["Case"]) == {"Q-missing-shipping-address", "Q-unknown-product"}


def test_editing_a_needs_info_case_supplies_the_address_and_prices_it(app):
    case_id = "Q-missing-shipping-address"
    app.run()
    app.session_state["selected_case"] = case_id
    app.run()
    assert not app.exception, [e.value for e in app.exception]

    next(b for b in app.button if b.label == "Edit case information").click().run()
    assert not app.exception, [e.value for e in app.exception]

    app.text_input(f"{case_id}-ship-line1").set_value("500 Harbour Road")
    app.text_input(f"{case_id}-ship-city").set_value("Seattle")
    app.text_input(f"{case_id}-ship-country").set_value("US")
    next(b for b in app.button if b.label == "Save changes").click().run()
    assert not app.exception, [e.value for e in app.exception]

    # priced and reviewable now, and gone from the Needs Info queue
    text = _markdown_text(app)
    assert "Pricing result" in text and "Pricing rationale" in text
    assert any(b.label == "Approve" for b in app.button)
    app.sidebar.radio[0].set_value("Needs Info").run()
    assert set(app.dataframe[0].value["Case"]) == {"Q-unknown-product"}


def test_selecting_a_case_shows_detail_and_approve_produces_quotation(app):
    app.run()
    app.session_state["selected_case"] = "Q-standard-quote"
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    text = _markdown_text(app)
    assert "Q-standard-quote" in text and "Pricing rationale" in text and "AI reviewer summary" in text
    # a draft is previewable before any decision, and is not yet stored on the case
    assert "Draft quote" in text and "Quotation Q-" in text
    assert any(b.label == "Download draft (md)" for b in app.download_button)

    next(b for b in app.button if b.label == "Approve").click().run()
    assert not app.exception, [e.value for e in app.exception]
    text = _markdown_text(app)
    assert "Quotation Q-" in text and "Superhero action jacket (Blue) M" in text

    app.sidebar.radio[0].set_value("Completed").run()
    assert list(app.dataframe[0].value["Case"]) == ["Q-standard-quote"]
