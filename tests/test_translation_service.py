from pathlib import Path

from eztrans.config import AppPaths, SettingsStore
from eztrans.models import ExampleSentence
from eztrans.services.dictionary_db import DictionaryDatabase
from eztrans.services.example_service import ExampleService
from eztrans.services.resource_manager import ResourceManager
from eztrans.services.translation_service import TranslationService


def _make_service(tmp_path):
    paths = AppPaths()
    paths.config_dir = tmp_path / "config"
    paths.data_dir = tmp_path / "data"
    paths.cache_dir = tmp_path / "cache"
    paths.logs_dir = paths.data_dir / "logs"
    paths.models_dir = paths.data_dir / "models"
    paths.db_dir = paths.data_dir / "db"
    paths.resources_dir = paths.data_dir / "resources"
    paths.temp_dir = paths.cache_dir / "tmp"
    paths.config_file = paths.config_dir / "settings.json"
    paths.dictionary_db = paths.db_dir / "dictionary.sqlite3"
    store = SettingsStore(paths)
    db = DictionaryDatabase(paths.dictionary_db)
    examples = ExampleService(db, Path("resources/seed_examples.json").resolve())
    rm = ResourceManager(paths, db, examples)
    settings = store.load()
    return TranslationService(db, rm, examples, settings)


def test_normalize_openai_base_url_trims_endpoint_suffixes(tmp_path):
    service = _make_service(tmp_path)
    assert service._normalize_openai_base_url("https://example.com/v1/chat/completions") == "https://example.com/v1"
    assert service._normalize_openai_base_url("https://example.com/v1/models") == "https://example.com/v1"


def test_candidate_openai_base_urls_adds_v1_fallback_for_root_url(tmp_path):
    service = _make_service(tmp_path)
    candidates = service._candidate_openai_base_urls("https://api.deepseek.com")
    assert candidates[:4] == [
        "https://api.deepseek.com",
        "https://api.deepseek.com/v1",
        "https://api.deepseek.com/api/v1",
        "https://api.deepseek.com/openai/v1",
    ]


def test_candidate_openai_base_urls_adds_glm_compat_path(tmp_path):
    service = _make_service(tmp_path)
    candidates = service._candidate_openai_base_urls("https://open.bigmodel.cn")
    assert "https://open.bigmodel.cn/api/paas/v4" in candidates


def test_candidate_openai_base_urls_adds_dashscope_compat_path(tmp_path):
    service = _make_service(tmp_path)
    candidates = service._candidate_openai_base_urls("https://dashscope.aliyuncs.com")
    assert "https://dashscope.aliyuncs.com/compatible-mode/v1" in candidates


def test_rank_models_prefers_glm_flash_for_bigmodel(tmp_path):
    service = _make_service(tmp_path)
    ranked = service._rank_models(
        ["embedding-3", "glm-4-flash", "glm-4"],
        "https://open.bigmodel.cn/api/paas/v4",
    )
    assert ranked[0] == "glm-4-flash"


def test_local_mode_does_not_generate_examples(tmp_path, monkeypatch):
    service = _make_service(tmp_path)
    monkeypatch.setattr(service.resource_manager, "translate_offline", lambda text, src, tgt: "hello there")
    monkeypatch.setattr(
        service,
        "_generate_ai_examples",
        lambda text, src, tgt, is_term_lookup: [
            ExampleSentence(src_lang=src, tgt_lang=tgt, source_text="a", target_text="b", source_name="ai")
        ],
    )

    result = service.translate("今天怎么样", "auto", "en", "local")

    assert result.examples == []
