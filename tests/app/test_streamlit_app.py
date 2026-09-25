"""Smoke-test the portal with Streamlit's headless AppTest: every navigation
screen renders without exceptions, the queues hold the right cases, a reviewer
edit completes a case, and Approve produces a quotation. Uses temp
catalog/case databases."""

from __future__ import annotations

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import quote_workflow.config as config

APP = Path(__file__).resolve().parents[2] / "app" / "streamlit_app.py"
SCREENS = ["my_queue", "all_cases", "needs_attention", "completed"]


@pytest.fixture
def app(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "CATALOG_DB_PATH", tmp_path / "catalog.db")
    monkeypatch.setattr(config, "CASES_DB_PATH", tmp_path / "cases.db")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ACCESS_CODE", raising=False)
    st.cache_resource.clear()  # the app caches the store/connection across runs
    yield AppTest.from_file(str(APP), default_timeout=120)
    st.cache_resource.clear()


def _markdown_text(app: AppTest) -> str:
    """Visible prose: card titles are markdown, disclaimers and metadata are captions."""
    return " ".join([*(m.value for m in app.markdown), *(c.value for c in app.caption)])


def _cases(app: AppTest) -> set[str]:
    return set(app.dataframe[0].value["Case"])


def _screen(app: AppTest, name: str) -> AppTest:
    app.switch_page(f"screens/{name}.py")
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def test_every_screen_renders_without_exceptions(app):
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    assert app.sidebar.segmented_control[0].value == "Sarah"
    for name in SCREENS:
        _screen(app, name)


def test_my_queue_lists_every_case_assigned_to_the_viewer(app):
    app.run()
    assert len(app.dataframe[0].value) == 8
    assert "Q-standard-quote" in _cases(app)


def test_needs_attention_holds_only_cases_a_human_must_act_on(app):
    app.run()
    _screen(app, "needs_attention")
    # the two incomplete samples, plus the three whose pricing needs a decision
    assert _cases(app) == {
        "Q-missing-shipping-address",
        "Q-unknown-product",
        "Q-below-floor",
        "Q-contract-below-floor",
        "Q-multi-line-program",
    }


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

    # priced and reviewable now, and no longer needing attention
    assert any(b.label == "Approve" for b in app.button)
    _screen(app, "needs_attention")
    assert case_id not in _cases(app)


def test_asking_ai_to_revise_parks_the_case_then_rework_returns_it_to_review(app):
    case_id = "Q-standard-quote"
    app.run()
    app.session_state["selected_case"] = case_id
    app.run()

    next(b for b in app.button if b.label == "Ask AI to Revise").click().run()
    assert not app.exception, [e.value for e in app.exception]
    app.text_area(f"{case_id}-revise-reason").set_value("The summary buries the thin margin")
    next(b for b in app.button if b.label == "Send back").click().run()
    assert not app.exception, [e.value for e in app.exception]

    # parked, visible as needing attention, and not approvable
    assert "Rework Requested" in _markdown_text(app) or any(
        "rework" in w.value.lower() for w in app.warning
    )
    assert not any(b.label == "Approve" for b in app.button)
    _screen(app, "needs_attention")
    assert case_id in _cases(app)

    _screen(app, "my_queue")
    next(b for b in app.button if b.label == "Run rework now").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert any(b.label == "Approve" for b in app.button)


def test_case_detail_shows_every_card_and_approve_produces_quotation(app):
    app.run()
    app.session_state["selected_case"] = "Q-standard-quote"
    app.run()
    assert not app.exception, [e.value for e in app.exception]

    text = _markdown_text(app)
    for card in (
        "Original RFQ",
        "Extracted Data",
        "Pricing Recommendation",
        "AI Reviewer Summary",
        "Validation & Warnings",
        "Processing Timeline",
        "Draft Quote",
    ):
        assert card in text, f"{card} card missing"
    # pricing is presented as deterministic, never as an AI recommendation
    assert "AI Pricing" not in text
    assert "Computed from pricing rules, not by the AI." in text
    assert any(b.label == "Download draft (md)" for b in app.download_button)

    next(b for b in app.button if b.label == "Approve").click().run()
    assert not app.exception, [e.value for e in app.exception]
    text = _markdown_text(app)
    assert "Quotation Q-" in text and "Superhero action jacket (Blue) M" in text

    _screen(app, "completed")
    assert _cases(app) == {"Q-standard-quote"}
