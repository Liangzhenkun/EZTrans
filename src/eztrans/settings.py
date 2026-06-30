from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .constants import DEFAULT_WINDOW_GEOMETRY


@dataclass(slots=True)
class AppSettings:
    source_lang: str = "auto"
    target_lang: str = "en"
    topmost: bool = True
    compact_view: bool = True
    translation_mode: str = "local"
    local_model_profile: str = "compact"
    online_enabled: bool = True
    auto_check_updates: bool = True
    auto_install_core_resources: bool = True
    hotkey: str = "ctrl+shift+t"
    geometry: str = DEFAULT_WINDOW_GEOMETRY
    github_repo: str = ""
    release_asset_name: str = ""
    libretranslate_url: str = ""
    openai_base_url: str = ""
    openai_api_key: str = ""
    openai_model: str = ""
    preferred_online_provider: str = "auto"
    preferred_example_provider: str = "tatoeba"
    speech_backend: str = "system"
    piper_model_path: str = ""
    piper_config_path: str = ""
    auto_export_history_path: str = ""
    last_update_check_iso: str = ""
    last_resource_sync_iso: str = ""
    installed_pairs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
