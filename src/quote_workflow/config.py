"""Paths and environment-driven settings, in one place.

Every module imports paths from here instead of recomputing ``Path(__file__)``
parents, and reads environment variables through these names instead of
``os.environ`` directly - so a deployment (Streamlit Cloud secrets, .env) only
has to satisfy one list, the one in ``.env.example``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

# src/quote_workflow/config.py -> parents[0]=quote_workflow, [1]=src, [2]=repo root
REPO_ROOT = Path(__file__).resolve().parents[2]

CONFIG_DIR = REPO_ROOT / "config"
POLICY_PATH = CONFIG_DIR / "policy.yaml"
INTAKE_CONFIG_PATH = CONFIG_DIR / "intake.yaml"

DATA_DIR = REPO_ROOT / "data"
REFERENCE_DIR = DATA_DIR / "reference"
SAMPLES_DIR = DATA_DIR / "samples"
SAMPLE_REQUESTS_PATH = SAMPLES_DIR / "requests.json"
DEMO_INBOX_PATH = SAMPLES_DIR / "demo_inbox.json"  # legacy mock mailbox (portal uses intake/)
INBOX_DIR = SAMPLES_DIR / "inbox"
INBOX_EXTRACTIONS_PATH = INBOX_DIR / "extractions.json"  # golden fallback for sample emails
DB_DIR = DATA_DIR / "db"
CATALOG_DB_PATH = DB_DIR / "catalog.db"  # reference data, rebuilt from CSVs
CASES_DB_PATH = DB_DIR / "cases.db"  # persisted QuoteCases, never rebuilt by build_db


def openai_model() -> str:
    return os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")


def default_reviewer() -> str:
    return os.environ.get("DEFAULT_REVIEWER", "Sarah")


@lru_cache
def _intake_config() -> dict:
    with INTAKE_CONFIG_PATH.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def intake_mailbox_address() -> str:
    """Public RFQ inbox customers send quote requests to."""
    return os.environ.get("INTAKE_MAILBOX_ADDRESS") or _intake_config()["mailbox"]["address"]


def intake_imap_host() -> str:
    return os.environ.get("INTAKE_IMAP_HOST") or _intake_config()["mailbox"]["imap"]["host"]


def intake_imap_port() -> int:
    raw = os.environ.get("INTAKE_IMAP_PORT")
    if raw:
        return int(raw)
    return int(_intake_config()["mailbox"]["imap"]["port"])


def intake_imap_folder() -> str:
    return os.environ.get("INTAKE_IMAP_FOLDER") or _intake_config()["mailbox"]["imap"]["folder"]


def intake_imap_password() -> str | None:
    """Gmail App Password (or other IMAP credential). Never commit this value."""
    return os.environ.get("INTAKE_IMAP_PASSWORD") or None


def intake_imap_enabled() -> bool:
    """True when live Gmail/IMAP polling is configured."""
    return bool(intake_imap_password())
