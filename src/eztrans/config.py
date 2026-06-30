from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path

from platformdirs import PlatformDirs

from .constants import APP_NAME
from .settings import AppSettings


class AppPaths:
    def __init__(self) -> None:
        dirs = PlatformDirs(APP_NAME, appauthor=False)
        self.config_dir = Path(dirs.user_config_dir)
        self.data_dir = Path(dirs.user_data_dir)
        self.cache_dir = Path(dirs.user_cache_dir)
        self.logs_dir = self.data_dir / "logs"
        self.models_dir = self.data_dir / "models"
        self.db_dir = self.data_dir / "db"
        self.resources_dir = self.data_dir / "resources"
        self.temp_dir = self.cache_dir / "tmp"
        self.config_file = self.config_dir / "settings.json"
        self.dictionary_db = self.db_dir / "dictionary.sqlite3"

    def ensure(self) -> None:
        for path in [
            self.config_dir,
            self.data_dir,
            self.cache_dir,
            self.logs_dir,
            self.models_dir,
            self.db_dir,
            self.resources_dir,
            self.temp_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)


class SettingsStore:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure()

    def load(self) -> AppSettings:
        if not self.paths.config_file.exists():
            settings = AppSettings()
            self.save(settings)
            return settings
        payload = json.loads(self.paths.config_file.read_text(encoding="utf-8"))
        defaults = AppSettings()
        data = defaults.to_dict()
        valid_fields = {item.name for item in fields(AppSettings)}
        for key, value in payload.items():
            if key in valid_fields:
                data[key] = value

        if "translation_mode" not in payload:
            has_ai_url = bool(payload.get("openai_base_url", "").strip())
            data["translation_mode"] = "ai" if has_ai_url else "local"
        if "local_model_profile" not in payload:
            data["local_model_profile"] = "compact"

        settings = AppSettings(**data)
        if settings.translation_mode not in {"local", "ai"}:
            settings.translation_mode = "local"
        return settings

    def save(self, settings: AppSettings) -> None:
        self.paths.config_file.write_text(
            json.dumps(settings.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
