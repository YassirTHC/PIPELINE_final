import ast
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

if "cv2" not in sys.modules:
    sys.modules["cv2"] = types.ModuleType("cv2")

moviepy_pkg = sys.modules.get("moviepy")
if moviepy_pkg is None:
    moviepy_pkg = types.ModuleType("moviepy")
    sys.modules["moviepy"] = moviepy_pkg
moviepy_pkg.__path__ = getattr(moviepy_pkg, "__path__", [])

moviepy_editor_mod = sys.modules.get("moviepy.editor")
if moviepy_editor_mod is None:
    moviepy_editor_mod = types.ModuleType("moviepy.editor")
    sys.modules["moviepy.editor"] = moviepy_editor_mod
setattr(moviepy_pkg, "editor", moviepy_editor_mod)


class _BaseDummyClip:
    def __init__(self, *_, **__):
        pass

    def close(self):
        pass


moviepy_editor_mod.VideoFileClip = _BaseDummyClip
moviepy_editor_mod.TextClip = _BaseDummyClip
moviepy_editor_mod.CompositeVideoClip = _BaseDummyClip

src_mod = sys.modules.get("src")
if src_mod is None:
    src_mod = types.ModuleType("src")
    sys.modules["src"] = src_mod
src_mod.__path__ = getattr(src_mod, "__path__", [])

pipeline_pkg = sys.modules.get("src.pipeline")
if pipeline_pkg is None:
    pipeline_pkg = types.ModuleType("src.pipeline")
    sys.modules["src.pipeline"] = pipeline_pkg
pipeline_pkg.__path__ = getattr(pipeline_pkg, "__path__", [])
setattr(src_mod, "pipeline", pipeline_pkg)

fetchers_mod = sys.modules.get("src.pipeline.fetchers")
if fetchers_mod is None:
    fetchers_mod = types.ModuleType("src.pipeline.fetchers")
    sys.modules["src.pipeline.fetchers"] = fetchers_mod
setattr(pipeline_pkg, "fetchers", fetchers_mod)

def _build_search_query_stub(keywords):
    return " ".join(keywords)


fetchers_mod.build_search_query = _build_search_query_stub
fetchers_mod.pexels_search_videos = lambda *_, **__: []
fetchers_mod.pixabay_search_videos = lambda *_, **__: []
fetchers_mod._best_vertical_video_file = lambda *_: {}
fetchers_mod._pixabay_best_video_url = lambda *_: None

llm_service_mod = types.ModuleType("pipeline_core.llm_service")


class _DummyLLMService:
    def __init__(self, *_, **__):
        pass

    def generate_metadata(self, *_, **__):
        return None

    def generate_hints_for_segment(self, *_, **__):
        return {}


llm_service_mod.LLMMetadataGeneratorService = _DummyLLMService
sys.modules["pipeline_core.llm_service"] = llm_service_mod

import video_processor
from config import Config
from pipeline_core.configuration import ProviderConfig


class DummyTranscriptSegment:
    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text


def _install_stub_modules():
    """Install minimal stub modules required by insert_brolls_if_enabled."""

    fake_modules: dict[str, types.ModuleType] = {}

    # moviepy.editor with VideoFileClip
    moviepy_mod = types.ModuleType("moviepy")
    moviepy_mod.__path__ = []  # mark as package
    moviepy_editor_mod = types.ModuleType("moviepy.editor")

    class _DummyVideoFileClip:
        def __init__(self, *_, **__):
            pass

        def close(self):
            pass

    moviepy_editor_mod.VideoFileClip = _DummyVideoFileClip
    moviepy_mod.editor = moviepy_editor_mod
    fake_modules["moviepy"] = moviepy_mod
    fake_modules["moviepy.editor"] = moviepy_editor_mod

    # src.pipeline package hierarchy
    src_mod = types.ModuleType("src")
    src_mod.__path__ = []
    pipeline_mod = types.ModuleType("src.pipeline")
    pipeline_mod.__path__ = []

    config_mod = types.ModuleType("src.pipeline.config")

    class _DummyBrollConfig:
        def __init__(self, *_, **__):
            pass

    config_mod.BrollConfig = _DummyBrollConfig

    keyword_mod = types.ModuleType("src.pipeline.keyword_extraction")

    def _dummy_extract_keywords_for_segment(*_, **__):
        return []

    keyword_mod.extract_keywords_for_segment = _dummy_extract_keywords_for_segment

    timeline_mod = types.ModuleType("src.pipeline.timeline_legacy")
    timeline_mod.plan_broll_insertions = lambda *_, **__: []
    timeline_mod.normalize_timeline = lambda *_, **__: []
    timeline_mod.enrich_keywords = lambda *_, **__: []

    renderer_mod = types.ModuleType("src.pipeline.renderer")
    renderer_mod.render_video = lambda *_, **__: None

    transcription_mod = types.ModuleType("src.pipeline.transcription")
    transcription_mod.TranscriptSegment = DummyTranscriptSegment

    indexer_mod = types.ModuleType("src.pipeline.indexer")
    indexer_mod.build_index = lambda *_, **__: None

    pipeline_mod.config = config_mod
    pipeline_mod.keyword_extraction = keyword_mod
    pipeline_mod.timeline_legacy = timeline_mod
    pipeline_mod.renderer = renderer_mod
    pipeline_mod.transcription = transcription_mod
    pipeline_mod.indexer = indexer_mod

    src_mod.pipeline = pipeline_mod

    fake_modules.update(
        {
            "src": src_mod,
            "src.pipeline": pipeline_mod,
            "src.pipeline.config": config_mod,
            "src.pipeline.keyword_extraction": keyword_mod,
            "src.pipeline.timeline_legacy": timeline_mod,
            "src.pipeline.renderer": renderer_mod,
            "src.pipeline.transcription": transcription_mod,
            "src.pipeline.indexer": indexer_mod,
        }
    )

    return fake_modules


class InsertBrollsProvidersTest(unittest.TestCase):
    def test_pipeline_core_skipped_when_no_enabled_providers(self):
        library_dir = Path("AI-B-roll/broll_library")
        library_dir.mkdir(parents=True, exist_ok=True)
        Config.TEMP_FOLDER.mkdir(parents=True, exist_ok=True)
        Config.CLIPS_FOLDER.mkdir(parents=True, exist_ok=True)

        input_path = Config.CLIPS_FOLDER / "reframed.mp4"
        input_path.parent.mkdir(parents=True, exist_ok=True)

        subtitles = [{"start": 0.0, "end": 1.0, "text": "Hello world"}]
        broll_keywords = ["keyword"]

        stub_modules = _install_stub_modules()

        result = None

        with patch.dict(sys.modules, stub_modules, clear=False):
            with patch("video_processor.whisper.load_model", return_value=object()):
                video_processor.VideoProcessor._setup_directories = lambda self: None
                video_processor.VideoProcessor._insert_brolls_pipeline_core = video_processor._insert_brolls_pipeline_core
                processor = video_processor.VideoProcessor()

            if not hasattr(video_processor.VideoProcessor, "insert_brolls_if_enabled"):
                source = Path(video_processor.__file__).read_text(encoding="utf-8")
                module_ast = ast.parse(source)
                target_node = None
                for node in ast.walk(module_ast):
                    if isinstance(node, ast.FunctionDef) and node.name == "insert_brolls_if_enabled":
                        target_node = node
                        break
                if target_node is None:
                    raise AssertionError("VideoProcessor.insert_brolls_if_enabled not available")
                new_module = ast.Module(body=[target_node], type_ignores=[])
                ast.fix_missing_locations(new_module)
                compiled = compile(new_module, video_processor.__file__, "exec")
                exec(compiled, video_processor.__dict__)
                setattr(video_processor.VideoProcessor, "insert_brolls_if_enabled", video_processor.__dict__["insert_brolls_if_enabled"])

            processor._pipeline_config.fetcher.providers = (
                ProviderConfig(name="stub", enabled=False),
            )

            with patch("video_processor._pipeline_core_fetcher_enabled", return_value=True):
                with patch.object(
                    video_processor.VideoProcessor,
                    "_insert_brolls_pipeline_core",
                    side_effect=AssertionError("pipeline core should not run"),
                ) as mock_pipeline_core:
                    with patch("src.pipeline.config.BrollConfig", side_effect=RuntimeError("stop")):
                        with self.assertLogs(video_processor.logger, level="WARNING") as log_ctx:
                            result = processor.insert_brolls_if_enabled(
                                input_path=input_path,
                                subtitles=subtitles,
                                broll_keywords=broll_keywords,
                            )

        mock_pipeline_core.assert_not_called()
        self.assertEqual(result, input_path)
        self.assertTrue(
            any("no providers are active" in message.lower() for message in log_ctx.output),
            "Expected warning about missing enabled providers",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
