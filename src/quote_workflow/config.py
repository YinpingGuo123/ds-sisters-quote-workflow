"""Paths and environment-driven settings, in one place.

Every module imports paths from here instead of recomputing ``Path(__file__)``
parents, and reads environment variables through these names instead of
``os.environ`` directly - so a deployment (Streamlit Cloud secrets, .env) only
has to satisfy one list, the one in ``.env.example``.
"""

from __future__ import annotations

import os
from pathlib import Path

# src/quote_workflow/config.py -> parents[0]=quote_workflow, [1]=src, [2]=repo root
REPO_ROOT = Path(__file__).resolve().parents[2]

CONFIG_DIR = REPO_ROOT / "config"
POLICY_PATH = CONFIG_DIR / "policy.yaml"

DATA_DIR = REPO_ROOT / "data"
REFERENCE_DIR = DATA_DIR / "reference"
SAMPLES_DIR = DATA_DIR / "samples"
SAMPLE_REQUESTS_PATH = SAMPLES_DIR / "requests.json"
DB_DIR = DATA_DIR / "db"
CATALOG_DB_PATH = DB_DIR / "catalog.db"  # reference data, rebuilt from CSVs
CASES_DB_PATH = DB_DIR / "cases.db"  # persisted QuoteCases, never rebuilt by build_db


def openai_model() -> str:
    return os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")


def default_reviewer() -> str:
    return os.environ.get("DEFAULT_REVIEWER", "Sarah")
