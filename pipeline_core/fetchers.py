"""Fetching orchestration helpers."""
from __future__ import annotations

import concurrent.futures
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from pipeline_core.configuration import FetcherOrchestratorConfig
from src.pipeline.fetchers import (  # type: ignore
    build_search_query,
    pexels_search_videos,
    pixabay_search_videos,
    _best_vertical_video_file,
    _pixabay_best_video_url,
)


@dataclass(slots=True)
class RemoteAssetCandidate:
    provider: str
    url: str
    thumb_url: Optional[str]
    width: int
    height: int
    duration: Optional[float]
    title: str
    identifier: str
    tags: Sequence[str]


class FetcherOrchestrator:
    """Thin orchestration layer for remote B-roll providers."""

    def __init__(self, config: FetcherOrchestratorConfig | None = None) -> None:
        self.config = config or FetcherOrchestratorConfig()

    def fetch_candidates(
        self,
        keywords: Sequence[str],
        *,
        duration_hint: Optional[float] = None,
        filters: Optional[dict] = None,
    ) -> List[RemoteAssetCandidate]:
        """Fetch candidates in parallel while respecting simple guard rails."""

        queries = self._build_queries(keywords)
        if not queries:
            return []

        providers = [p for p in self.config.providers if p.enabled]
        if not providers:
            return []

        start = time.perf_counter()
        results: List[RemoteAssetCandidate] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.config.parallel_requests or 1) as pool:
            futures = []
            for provider_conf in providers:
                for query in queries:
                    futures.append(
                        pool.submit(self._run_provider_fetch, provider_conf, query, filters)
                    )

            timeout_s = max(self.config.request_timeout_s, 0.1)
            deadline = start + timeout_s
            pending = set(futures)
            while pending and len(results) < self.config.per_segment_limit:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    break
                done, pending = concurrent.futures.wait(
                    pending,
                    timeout=remaining,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                if not done:
                    break
                for fut in done:
                    try:
                        candidates = fut.result() or []
                    except concurrent.futures.TimeoutError:
                        continue
                    except Exception:
                        continue
                    if not candidates:
                        continue
                    for candidate in candidates:
                        if self._candidate_passes_filters(candidate, filters, duration_hint):
                            results.append(candidate)
                            if len(results) >= self.config.per_segment_limit:
                                break
            for fut in pending:
                fut.cancel()

        return results[: self.config.per_segment_limit]

    # ------------------------------------------------------------------
    # Provider fetch helpers
    # ------------------------------------------------------------------
    def _run_provider_fetch(self, provider_conf, query: str, filters: Optional[dict]) -> List[RemoteAssetCandidate]:
        name = provider_conf.name.lower()
        limit = max(1, provider_conf.max_results or self.config.per_segment_limit)
        timeout = provider_conf.timeout_s or self.config.request_timeout_s
        timeout = max(timeout, 0.1)
        attempts = max(1, self.config.retry_count)

        def _dispatch() -> List[RemoteAssetCandidate]:
            if name == "pexels":
                return self._fetch_from_pexels(query, limit, timeout_s=timeout)
            if name == "pixabay":
                return self._fetch_from_pixabay(query, limit, timeout_s=timeout)
            return []

        for attempt in range(attempts):
            gate = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = gate.submit(_dispatch)
            try:
                result = future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                future.cancel()
                gate.shutdown(wait=False, cancel_futures=True)
                continue
            except Exception:
                gate.shutdown(wait=False, cancel_futures=True)
                if attempt == attempts - 1:
                    return []
                continue
            else:
                gate.shutdown(wait=True, cancel_futures=False)
                return result
        return []

    def _fetch_from_pexels(
        self, query: str, limit: int, *, timeout_s: Optional[float] = None
    ) -> List[RemoteAssetCandidate]:
        key = getattr(__import__("config", fromlist=["Config"]).Config, "PEXELS_API_KEY", None)
        if not key:
            return []
        try:
            kwargs = {"per_page": limit * 2}
            if timeout_s is not None:
                kwargs["timeout"] = timeout_s
            videos = pexels_search_videos(key, query, **kwargs)
        except Exception:
            return []
        candidates: List[RemoteAssetCandidate] = []
        for item in videos:
            best = _best_vertical_video_file(item)
            if not best:
                continue
            url = best.get("link") or best.get("file")
            if not url:
                continue
            candidates.append(
                RemoteAssetCandidate(
                    provider="pexels",
                    url=url,
                    thumb_url=(item.get("image") or None),
                    width=int(best.get("width", 0) or 0),
                    height=int(best.get("height", 0) or 0),
                    duration=float(item.get("duration", 0.0) or 0.0),
                    title=str(item.get("user", {}).get("name", "")),
                    identifier=str(item.get("id", "")),
                    tags=[t.get("title", "") for t in item.get("tags", []) if t.get("title")],
                )
            )
        return candidates

    def _fetch_from_pixabay(
        self, query: str, limit: int, *, timeout_s: Optional[float] = None
    ) -> List[RemoteAssetCandidate]:
        key = getattr(__import__("config", fromlist=["Config"]).Config, "PIXABAY_API_KEY", None)
        if not key:
            return []
        try:
            kwargs = {"per_page": limit * 2}
            if timeout_s is not None:
                kwargs["timeout"] = timeout_s
            videos = pixabay_search_videos(key, query, **kwargs)
        except Exception:
            return []
        candidates: List[RemoteAssetCandidate] = []
        for item in videos:
            url = _pixabay_best_video_url(item)
            if not url:
                continue
            videos_meta = item.get("videos", {}) or {}
            best_meta = videos_meta.get("large") or videos_meta.get("medium") or {}
            candidates.append(
                RemoteAssetCandidate(
                    provider="pixabay",
                    url=url,
                    thumb_url=item.get("picture_id"),
                    width=int(best_meta.get("width", 0) or 0),
                    height=int(best_meta.get("height", 0) or 0),
                    duration=None,
                    title=item.get("user", ""),
                    identifier=str(item.get("id", "")),
                    tags=[tag.strip() for tag in (item.get("tags", "") or "").split(",") if tag.strip()],
                )
            )
        return candidates

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def _build_queries(self, keywords: Sequence[str]) -> List[str]:
        normalized = [kw.strip() for kw in keywords if isinstance(kw, str) and kw.strip()]
        if not normalized:
            return []
        primary = build_search_query(normalized)
        queries = [primary] if primary else []
        # Add up to 3 secondary queries to diversify results
        for kw in normalized:
            if kw not in queries:
                queries.append(kw)
            if len(queries) >= 4:
                break
        return queries

    def _candidate_passes_filters(
        self,
        candidate: RemoteAssetCandidate,
        filters: Optional[dict],
        duration_hint: Optional[float],
    ) -> bool:
        if not candidate.url:
            return False
        orientation = None
        min_duration = None
        if filters:
            orientation = filters.get("orientation")
            min_duration = filters.get("min_duration_s")
        if orientation == "landscape" and candidate.width and candidate.height:
            if candidate.width < candidate.height:
                return False
        if orientation == "portrait" and candidate.width and candidate.height:
            if candidate.height < candidate.width:
                return False
        target_min = min_duration if isinstance(min_duration, (int, float)) else None
        if target_min is None and duration_hint:
            target_min = max(0.0, float(duration_hint))
        if target_min and candidate.duration and candidate.duration < target_min:
            return False
        return True
