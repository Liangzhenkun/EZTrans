from __future__ import annotations

from pathlib import Path

import requests

from ..constants import APP_VERSION, GITHUB_API_BASE
from ..models import AppUpdateInfo
from ..settings import AppSettings
from .resource_manager import ResourceManager


class UpdateService:
    def __init__(self, resource_manager: ResourceManager) -> None:
        self.resource_manager = resource_manager

    def check_app_update(self, settings: AppSettings) -> AppUpdateInfo:
        if not settings.github_repo:
            return AppUpdateInfo(has_update=False, current_version=APP_VERSION)
        response = requests.get(
            f"{GITHUB_API_BASE}/repos/{settings.github_repo}/releases/latest",
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        latest = payload.get("tag_name", "").lstrip("v")
        assets = payload.get("assets", [])
        download_url = ""
        if settings.release_asset_name:
            for asset in assets:
                if asset.get("name") == settings.release_asset_name:
                    download_url = asset.get("browser_download_url", "")
                    break
        elif assets:
            download_url = assets[0].get("browser_download_url", "")
        has_update = bool(latest and latest != APP_VERSION)
        return AppUpdateInfo(
            has_update=has_update,
            current_version=APP_VERSION,
            latest_version=latest,
            download_url=download_url,
            notes=payload.get("body", "")[:500],
        )

    def download_app_update(self, info: AppUpdateInfo, destination_dir: Path) -> Path | None:
        if not info.download_url:
            return None
        destination_dir.mkdir(parents=True, exist_ok=True)
        filename = info.download_url.rsplit("/", 1)[-1]
        target = destination_dir / filename
        response = requests.get(info.download_url, timeout=120)
        response.raise_for_status()
        target.write_bytes(response.content)
        return target
