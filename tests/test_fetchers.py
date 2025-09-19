"""Tests for the fetcher orchestrator timeout handling."""

from __future__ import annotations

import sys
import time
import types
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Provide a lightweight stub for ``src.pipeline.fetchers`` so the orchestrator
# can import the expected helpers without depending on the original project
# layout. The production code only needs a couple of callables, so we expose
# no-op implementations that tests can monkeypatch as required.
# ---------------------------------------------------------------------------
src_module = sys.modules.setdefault("src", types.ModuleType("src"))
if not hasattr(src_module, "__path__"):
    src_module.__path__ = []  # type: ignore[attr-defined]

pipeline_module = sys.modules.setdefault("src.pipeline", types.ModuleType("src.pipeline"))
if not hasattr(pipeline_module, "__path__"):
    pipeline_module.__path__ = []  # type: ignore[attr-defined]
setattr(src_module, "pipeline", pipeline_module)

fetchers_stub = sys.modules.setdefault(
    "src.pipeline.fetchers", types.ModuleType("src.pipeline.fetchers")
)
setattr(pipeline_module, "fetchers", fetchers_stub)


def _default_build_search_query(keywords):  # pragma: no cover - trivial helper
    return " ".join(keywords)


if not hasattr(fetchers_stub, "build_search_query"):
    fetchers_stub.build_search_query = _default_build_search_query
if not hasattr(fetchers_stub, "pexels_search_videos"):
    fetchers_stub.pexels_search_videos = lambda *args, **kwargs: []
if not hasattr(fetchers_stub, "pixabay_search_videos"):
    fetchers_stub.pixabay_search_videos = lambda *args, **kwargs: []
if not hasattr(fetchers_stub, "_best_vertical_video_file"):
    fetchers_stub._best_vertical_video_file = lambda item: {}
if not hasattr(fetchers_stub, "_pixabay_best_video_url"):
    fetchers_stub._pixabay_best_video_url = lambda item: None


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline_core import fetchers as fetchers_module
from pipeline_core.configuration import FetcherOrchestratorConfig, ProviderConfig


def test_run_provider_fetch_timeout_cancels_quickly(monkeypatch):
    """Slow providers should be abandoned as soon as the timeout elapses."""

    orchestrator = fetchers_module.FetcherOrchestrator(
        FetcherOrchestratorConfig(
            providers=[ProviderConfig(name="pexels", timeout_s=0.3, max_results=1)],
            per_segment_limit=1,
            parallel_requests=1,
            retry_count=1,
            request_timeout_s=0.3,
        )
    )

    def slow_fetch(self, query, limit, *, timeout_s=None):  # pragma: no cover - patched
        time.sleep(2.0)
        return []

    monkeypatch.setattr(
        fetchers_module.FetcherOrchestrator,
        "_fetch_from_pexels",
        slow_fetch,
        raising=False,
    )

    start = time.perf_counter()
    results = orchestrator.fetch_candidates(["slow provider"])
    elapsed = time.perf_counter() - start

    assert results == []
    assert elapsed < 1.0, "orchestrator waited for the slow provider to finish"


def test_timeout_forwarded_to_provider_helpers(monkeypatch):
    """Per-provider timeouts must reach the provider API helpers."""

    import config

    calls: list[float | None] = []

    def fake_search(api_key, query, *, per_page, timeout=None):
        calls.append(timeout)
        return []

    monkeypatch.setattr(fetchers_module, "pexels_search_videos", fake_search)
    monkeypatch.setattr(config.Config, "PEXELS_API_KEY", "token", raising=False)

    orchestrator = fetchers_module.FetcherOrchestrator(
        FetcherOrchestratorConfig(
            providers=[ProviderConfig(name="pexels", timeout_s=0.7, max_results=1)],
            per_segment_limit=1,
            parallel_requests=1,
            retry_count=1,
            request_timeout_s=0.7,
        )
    )

    orchestrator.fetch_candidates(["topic"])

    assert calls, "provider helper was not invoked"
    assert calls[0] == pytest.approx(0.7)
