"""Sample structured requests (data/samples/requests.json) for seeding demo
cases. Names, not ids: the seed path resolves them through the catalog, the
same way an intake implementation might."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from quote_workflow.catalog.resolution import resolve
from quote_workflow.config import SAMPLE_REQUESTS_PATH
from quote_workflow.contracts.quote_request import QuoteRequest


def load_samples(path: Path = SAMPLE_REQUESTS_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def sample_request(sample: dict, conn: sqlite3.Connection) -> QuoteRequest:
    """The sample's request, resolved against the catalog."""
    return resolve(conn, QuoteRequest.model_validate(sample["request"]))
