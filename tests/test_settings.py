from eztrans.config import AppPaths, SettingsStore


def test_settings_store_round_trip(tmp_path):
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
    settings = store.load()
    settings.target_lang = "fi"
    settings.hotkey = "ctrl+alt+z"
    settings.compact_view = False
    settings.translation_mode = "ai"
    settings.local_model_profile = "balanced"
    store.save(settings)

    loaded = store.load()
    assert loaded.target_lang == "fi"
    assert loaded.hotkey == "ctrl+alt+z"
    assert loaded.compact_view is False
    assert loaded.translation_mode == "ai"
    assert loaded.local_model_profile == "balanced"


def test_settings_store_migrates_missing_new_fields(tmp_path):
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
    paths.ensure()
    paths.config_file.write_text(
        '{"target_lang":"en","openai_base_url":"https://api.deepseek.com/v1"}',
        encoding="utf-8",
    )

    store = SettingsStore(paths)
    loaded = store.load()

    assert loaded.compact_view is True
    assert loaded.translation_mode == "ai"
    assert loaded.local_model_profile == "compact"
