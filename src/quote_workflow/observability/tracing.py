"""Langfuse observability setup (starting point, carried over from the POC).

Not wired into the pipeline yet: where spans go (workflow stages, catalog
lookups, the explain call) is the observability owner's call. Everything
here is optional - the ``observability`` extra must be installed to use it.

Call :func:`configure` at the start of any public entry point, before any
Langfuse-wrapped OpenAI client is constructed - it loads .env and bridges
env var naming, which must happen first per Langfuse's own "wrong import
order" guidance. Safe to call many times (cached).

If Langfuse keys are missing or invalid, the app still runs - traces are
simply not sent. Nothing here ever raises due to missing/invalid credentials.
"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

# Attached to every trace as the release/version, so behavior can be compared
# across versions in the Langfuse UI. Bump alongside pyproject.toml's version.
APP_VERSION = "0.1.0"


def _bridge_host_env() -> None:
    """Accept either LANGFUSE_HOST or LANGFUSE_BASE_URL and keep both in sync.

    The Python SDK reads LANGFUSE_HOST; this project's .env.example uses
    LANGFUSE_BASE_URL. Supporting both avoids a confusing
    "why are there no traces" moment.
    """
    host = os.environ.get("LANGFUSE_HOST")
    base_url = os.environ.get("LANGFUSE_BASE_URL")
    if not host and base_url:
        os.environ["LANGFUSE_HOST"] = base_url
    elif host and not base_url:
        os.environ["LANGFUSE_BASE_URL"] = host


@lru_cache(maxsize=1)
def configure():
    """Initialize Langfuse once. Returns the client, or None if unavailable."""
    load_dotenv()
    _bridge_host_env()

    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception as exc:  # pragma: no cover - defensive, keeps app usable
        print(f"[observability] truststore not active ({exc}); relying on certifi roots.")

    os.environ.setdefault("LANGFUSE_TRACING_ENVIRONMENT", "development")
    os.environ.setdefault("LANGFUSE_RELEASE", APP_VERSION)

    try:
        from langfuse import get_client
    except Exception as exc:  # pragma: no cover
        print(f"[observability] Langfuse SDK not available: {exc}")
        return None

    client = get_client()
    try:
        authed = client.auth_check()
    except Exception as exc:  # network/SSL/host problems must not crash the app
        print(f"[observability] Langfuse auth check failed ({exc}); traces may not be sent.")
        return client

    if authed:
        print(
            f"[observability] Langfuse ready (env={os.environ['LANGFUSE_TRACING_ENVIRONMENT']}, release={APP_VERSION})"
        )
    else:
        print(
            "[observability] Langfuse credentials missing or invalid - traces will "
            "not be sent. Set LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL."
        )
    return client


def flush() -> None:
    """Flush buffered traces. Call before a short-lived process exits."""
    client = configure()
    if client is not None:
        client.flush()
