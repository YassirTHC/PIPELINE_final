import time

import pytest

from pipeline_core.configuration import FetcherOrchestratorConfig, ProviderConfig
from pipeline_core.fetchers import FetcherOrchestrator, RemoteAssetCandidate


def _make_candidate(provider: str) -> RemoteAssetCandidate:
    return RemoteAssetCandidate(
        provider=provider,
        url=f"https://example.com/{provider}",
        thumb_url=None,
        width=1080,
        height=1920,
        duration=None,
        title=f"{provider} clip",
        identifier=provider,
        tags=(provider,),
    )


def test_fetch_candidates_skips_slow_provider(monkeypatch):
    config = FetcherOrchestratorConfig(
        providers=(
            ProviderConfig(name="pexels", timeout_s=0.05, retry_count=0),
            ProviderConfig(name="pixabay", timeout_s=0.5, retry_count=0),
        ),
        request_timeout_s=0.5,
        per_segment_limit=2,
        parallel_requests=2,
    )
    orchestrator = FetcherOrchestrator(config)

    call_count = {"pexels": 0}
    slow_timeouts = []
    fast_timeouts = []

    def slow_fetch(self, query, limit, *, timeout_s=None):
        call_count["pexels"] += 1
        slow_timeouts.append(timeout_s)
        time.sleep(0.2)
        raise TimeoutError("slow provider")

    def fast_fetch(self, query, limit, *, timeout_s=None):
        fast_timeouts.append(timeout_s)
        return [_make_candidate("pixabay")]

    monkeypatch.setattr(
        FetcherOrchestrator, "_fetch_from_pexels", slow_fetch, raising=True
    )
    monkeypatch.setattr(
        FetcherOrchestrator, "_fetch_from_pixabay", fast_fetch, raising=True
    )

    start = time.perf_counter()
    results = orchestrator.fetch_candidates(["nature"])
    elapsed = time.perf_counter() - start

    assert elapsed < 0.2, "slow provider should be timed out using its own budget"
    assert [candidate.provider for candidate in results] == ["pixabay"]
    assert call_count["pexels"] == 1
    # The orchestrator enforces a minimal timeout budget of 0.1 seconds per request.
    assert slow_timeouts and abs(slow_timeouts[0] - 0.1) < 0.02
    assert fast_timeouts and abs(fast_timeouts[0] - 0.5) < 0.1


def test_run_provider_fetch_honours_retry_count(monkeypatch):
    provider = ProviderConfig(name="pexels", timeout_s=0.2, retry_count=2)
    config = FetcherOrchestratorConfig(
        providers=(provider,),
        retry_count=0,  # global fallback should not override provider-specific value
    )
    orchestrator = FetcherOrchestrator(config)

    attempts = []

    def flaky_fetch(self, query, limit, *, timeout_s=None):
        attempts.append(timeout_s)
        if len(attempts) < 3:
            raise RuntimeError("temporary error")
        return [_make_candidate("pexels")]

    monkeypatch.setattr(
        FetcherOrchestrator, "_fetch_from_pexels", flaky_fetch, raising=True
    )

    result = orchestrator._run_provider_fetch(provider, "city", None)

    assert len(attempts) == 3
    assert all(abs(timeout - 0.2) < 0.05 for timeout in attempts)
    assert result and result[0].provider == "pexels"
