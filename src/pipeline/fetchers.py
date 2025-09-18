from __future__ import annotations

from typing import Iterable, List


def build_search_query(keywords: Iterable[str]) -> str:
    return " ".join(keywords)


def pexels_search_videos(api_key: str, query: str, **kwargs) -> List[dict]:
    return []


def pixabay_search_videos(api_key: str, query: str, **kwargs) -> List[dict]:
    return []


def _best_vertical_video_file(item: dict) -> dict:
    return {}


def _pixabay_best_video_url(item: dict) -> str:
    return ""
