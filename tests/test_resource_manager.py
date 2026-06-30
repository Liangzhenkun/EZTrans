from pathlib import Path

from eztrans.config import AppPaths
from eztrans.services.dictionary_db import DictionaryDatabase
from eztrans.services.example_service import ExampleService
from eztrans.services.resource_manager import ResourceManager


def _make_resource_manager(tmp_path):
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
    db = DictionaryDatabase(paths.dictionary_db)
    examples = ExampleService(db, Path("resources/seed_examples.json").resolve())
    return ResourceManager(paths, db, examples)


def test_segmented_offline_translation_preserves_multiple_clauses(tmp_path, monkeypatch):
    manager = _make_resource_manager(tmp_path)
    monkeypatch.setattr(manager, "ensure_pair_resources", lambda src, tgt: [])

    mapping = {
        "今天吃的炖排骨": "The stewed ribs I ate today",
        "这是我最爱吃的菜": "This is my favorite dish",
    }

    def fake_translate_core(text, src_lang, tgt_lang):
        return mapping.get(text)

    monkeypatch.setattr(manager, "_translate_offline_core", fake_translate_core)

    translated = manager.translate_offline("今天吃的炖排骨，这是我最爱吃的菜", "zh", "en")

    assert translated == "The stewed ribs I ate today, This is my favorite dish"
