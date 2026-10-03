"""Deterministic extractions for the sample inbox when no LLM key is configured.

Golden fields live in ``data/samples/inbox/extractions.json`` keyed by file
name (``source_id``). Used in CI and local runs without ``OPENAI_API_KEY``.
"""

from __future__ import annotations

import json
from pathlib import Path

from quote_workflow.config import INBOX_EXTRACTIONS_PATH
from quote_workflow.intake.output import LlmExtractedRfq


def _load_extractions(path: Path = INBOX_EXTRACTIONS_PATH) -> dict[str, dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def fallback_extract(source_id: str, path: Path = INBOX_EXTRACTIONS_PATH) -> LlmExtractedRfq:
    """Return the canned extraction for a known inbox sample."""
    data = _load_extractions(path)
    if source_id not in data:
        raise KeyError(f"no fallback extraction for {source_id!r}; set OPENAI_API_KEY or add it to {path.name}")
    return LlmExtractedRfq.model_validate(data[source_id])
