"""Shared configuration dataclasses for the modular video pipeline.

These helpers centralise the defaults we want to reuse while we
progressively refactor the monolithic `VideoProcessor`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from config import Config


@dataclass(slots=True)
class PipelinePaths:
    """Local directories used by the pipeline.

    The defaults are aligned with the existing ``Config`` class so that the
    new modules remain drop-in replacements for the current behaviour.
    """

    clips_dir: Path = field(default_factory=lambda: Config.CLIPS_FOLDER)
    output_dir: Path = field(default_factory=lambda: Config.OUTPUT_FOLDER)
    temp_dir: Path = field(default_factory=lambda: Config.TEMP_FOLDER)


@dataclass(slots=True)
class ProviderConfig:
    """Configuration for a single external media provider."""

    name: str
    weight: float = 1.0
    enabled: bool = True
    max_results: int = 6
    timeout_s: float = 8.0
    retry_count: int = 2


@dataclass(slots=True)
class FetcherOrchestratorConfig:
    """Controls how the orchestrator queries the external APIs."""

    providers: Sequence[ProviderConfig] = field(
        default_factory=lambda: (
            ProviderConfig(name="pexels", weight=1.0, max_results=6),
            ProviderConfig(name="pixabay", weight=0.9, max_results=6),
        )
    )
    per_segment_limit: int = 6
    parallel_requests: int = 4
    allow_images: bool = True
    allow_videos: bool = True
    retry_count: int = 2
    request_timeout_s: float = 8.0


@dataclass(slots=True)
class SelectionConfig:
    """Selection guard-rails applied after ranking."""

    min_score: float = 0.54
    prefer_landscape: bool = True
    min_duration_s: float = 3.0
    require_license_ok: bool = True


@dataclass(slots=True)
class OrchestratorRuntimeConfig:
    """Runtime tuning for the orchestrator."""

    max_segments_in_flight: int = 2


@dataclass(slots=True)
class TimeboxingConfig:
    """Timeout thresholds (in milliseconds)."""

    fetch_rank_ms: int = 3000


@dataclass(slots=True)
class DedupePolicy:
    """Defines how we detect duplicates within a single video."""

    enable_url_tracking: bool = True
    enable_phash: bool = True
    phash_distance: int = 6
    title_similarity_threshold: float = 0.85


@dataclass(slots=True)
class LLMServiceConfig:
    """Runtime settings for the LLM keyword/metadata generator."""

    provider_name: str = "pipeline_integration"
    max_queries_per_segment: int = 6
    include_bigrams: bool = True
    include_trigrams: bool = True
    cache_ttl_s: float = 15 * 60  # 15 minutes


@dataclass(slots=True)
class RendererConfig:
    """Configuration shared by the rendering subsystem."""

    crossfade_ms: int = 320
    pad_in_s: float = 0.25
    pad_out_s: float = 0.25
    min_duration_s: float = 2.0
    prefer_streaming: bool = True


@dataclass(slots=True)
class PipelineConfigBundle:
    """Aggregates the sub-configs for convenience."""

    paths: PipelinePaths = field(default_factory=PipelinePaths)
    fetcher: FetcherOrchestratorConfig = field(default_factory=FetcherOrchestratorConfig)
    selection: SelectionConfig = field(default_factory=SelectionConfig)
    orchestrator: OrchestratorRuntimeConfig = field(default_factory=OrchestratorRuntimeConfig)
    timeboxing: TimeboxingConfig = field(default_factory=TimeboxingConfig)
    dedupe: DedupePolicy = field(default_factory=DedupePolicy)
    llm: LLMServiceConfig = field(default_factory=LLMServiceConfig)
    renderer: RendererConfig = field(default_factory=RendererConfig)
