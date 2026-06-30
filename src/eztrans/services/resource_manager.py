from __future__ import annotations

import re
import socket
from pathlib import Path

import argostranslate.package
import argostranslate.translate

from ..config import AppPaths
from ..constants import LOCAL_MODEL_PROFILES, OFFLINE_LANGUAGE_CODES, RESOURCE_KEYS
from ..models import UpdateItem
from ..settings import AppSettings
from .dictionary_db import DictionaryDatabase
from .example_service import ExampleService
from .importers import download_and_parse_cedict, download_and_parse_freedict


class ResourceManager:
    def __init__(
        self,
        paths: AppPaths,
        db: DictionaryDatabase,
        examples: ExampleService,
    ) -> None:
        self.paths = paths
        self.db = db
        self.examples = examples

    def is_online(self) -> bool:
        try:
            socket.create_connection(("api.github.com", 443), timeout=3).close()
            return True
        except OSError:
            return False

    def bootstrap(self, settings: AppSettings, progress: callable | None = None) -> list[str]:
        notes: list[str] = []
        self.paths.ensure()
        online = self.is_online()
        example_count = self.examples.bootstrap_seed_examples()
        if example_count and progress:
            progress(f"Imported {example_count} seed examples.")
        if self.db.get_resource_status(RESOURCE_KEYS["cedict"]) is None and online:
            if progress:
                progress("Downloading CC-CEDICT...")
            zh_entries, en_entries = download_and_parse_cedict()
            self.db.import_dictionary_entries(zh_entries, "dictionary:cedict:zh-en", "1")
            self.db.import_dictionary_entries(en_entries, "dictionary:cedict:en-zh", "1")
            self.db.set_resource_status(RESOURCE_KEYS["cedict"], "1")
            notes.append("CC-CEDICT installed.")
        if settings.auto_install_core_resources and online:
            profile_notes = self.ensure_local_profile(settings.local_model_profile, progress=progress)
            if profile_notes:
                notes.extend(profile_notes)
            else:
                notes.append("Local translation models are ready.")
        return notes

    def _installed_argos_pairs(self) -> set[tuple[str, str]]:
        packages = argostranslate.package.get_installed_packages()
        return {(pkg.from_code, pkg.to_code) for pkg in packages}

    def get_installed_argos_pairs(self) -> set[tuple[str, str]]:
        return self._installed_argos_pairs()

    def _available_argos_package(self, src_lang: str, tgt_lang: str):
        packages = argostranslate.package.get_available_packages()
        return next(
            (pkg for pkg in packages if pkg.from_code == src_lang and pkg.to_code == tgt_lang),
            None,
        )

    def ensure_local_profile(self, profile_key: str, progress: callable | None = None) -> list[str]:
        profile = LOCAL_MODEL_PROFILES.get(profile_key) or LOCAL_MODEL_PROFILES["compact"]
        notes: list[str] = []
        for src_lang, tgt_lang in profile["pairs"]:
            if progress:
                progress(f"Installing local model {src_lang}->{tgt_lang}...")
            self._ensure_argos_pair(src_lang, tgt_lang, notes)
        return notes

    def ensure_pair_resources(self, src_lang: str, tgt_lang: str) -> list[str]:
        installed: list[str] = []
        if src_lang == tgt_lang:
            return installed
        if src_lang in OFFLINE_LANGUAGE_CODES and tgt_lang in OFFLINE_LANGUAGE_CODES:
            self._ensure_argos_pair(src_lang, tgt_lang, installed)
        if (src_lang, tgt_lang) in [("zh", "en"), ("en", "zh")]:
            return installed
        if (src_lang, tgt_lang) in [("en", "fi"), ("fi", "en"), ("en", "sv"), ("sv", "en"), ("en", "da"), ("da", "en"), ("en", "nb")]:
            self._ensure_freedict_pair(src_lang, tgt_lang, installed)
        return installed

    def _ensure_argos_pair(self, src_lang: str, tgt_lang: str, notes: list[str]) -> None:
        installed_pairs = self._installed_argos_pairs()
        if (src_lang, tgt_lang) in installed_pairs:
            return
        package = self._available_argos_package(src_lang, tgt_lang)
        if package is None:
            if src_lang != "en" and tgt_lang != "en":
                self._ensure_argos_pair(src_lang, "en", notes)
                self._ensure_argos_pair("en", tgt_lang, notes)
            return
        download_path = package.download()
        argostranslate.package.install_from_path(download_path)
        notes.append(f"Installed offline model {src_lang}->{tgt_lang}.")

    def _ensure_freedict_pair(self, src_lang: str, tgt_lang: str, notes: list[str]) -> None:
        key = f"dictionary:freedict:{src_lang}-{tgt_lang}"
        if self.db.get_resource_status(key) is not None:
            return
        version, entries = download_and_parse_freedict(src_lang, tgt_lang)
        self.db.import_dictionary_entries(entries, key, version)
        notes.append(f"Installed dictionary {src_lang}->{tgt_lang}.")

    def check_model_updates(self) -> list[UpdateItem]:
        installed = argostranslate.package.get_installed_packages()
        available = {
            (pkg.from_code, pkg.to_code): pkg
            for pkg in argostranslate.package.get_available_packages()
        }
        updates: list[UpdateItem] = []
        for pkg in installed:
            candidate = available.get((pkg.from_code, pkg.to_code))
            if candidate and candidate.package_version != pkg.package_version:
                updates.append(
                    UpdateItem(
                        kind="model",
                        identifier=f"{pkg.from_code}->{pkg.to_code}",
                        current_version=pkg.package_version,
                        latest_version=candidate.package_version,
                        notes="Argos package update available.",
                    )
                )
        return updates

    def apply_model_updates(self) -> list[str]:
        installed = argostranslate.package.get_installed_packages()
        available = {
            (pkg.from_code, pkg.to_code): pkg
            for pkg in argostranslate.package.get_available_packages()
        }
        notes: list[str] = []
        for pkg in installed:
            candidate = available.get((pkg.from_code, pkg.to_code))
            if candidate and candidate.package_version != pkg.package_version:
                download_path = candidate.download()
                argostranslate.package.install_from_path(download_path)
                notes.append(f"Updated model {pkg.from_code}->{pkg.to_code} to {candidate.package_version}.")
        return notes

    def translate_offline(self, text: str, src_lang: str, tgt_lang: str) -> str:
        self.ensure_pair_resources(src_lang, tgt_lang)
        if src_lang == tgt_lang:
            return text
        segmented = self._translate_by_segments(text, src_lang, tgt_lang)
        if segmented:
            return segmented
        direct = self._translate_offline_core(text, src_lang, tgt_lang)
        return direct or text

    def _translate_offline_core(self, text: str, src_lang: str, tgt_lang: str) -> str | None:
        direct = self._direct_translate(text, src_lang, tgt_lang)
        if direct is not None:
            return direct
        if src_lang != "en" and tgt_lang != "en":
            first = self._direct_translate(text, src_lang, "en") or text
            second = self._direct_translate(first, "en", tgt_lang) or first
            return second
        return None

    def _translate_by_segments(self, text: str, src_lang: str, tgt_lang: str) -> str | None:
        if len(text.strip()) < 8:
            return None
        if not re.search(r"[，,。.!？?；;:\n]", text):
            return None
        parts = re.split(r"([，,。.!？?；;:\n])", text)
        text_segments = [part for part in parts if part.strip() and not re.fullmatch(r"[，,。.!？?；;:\n]", part)]
        if len(text_segments) < 2:
            return None
        translated_parts: list[str] = []
        for part in parts:
            if not part:
                continue
            if re.fullmatch(r"[，,。.!？?；;:\n]", part):
                translated_parts.append(self._map_punctuation(part, tgt_lang))
                continue
            if not part.strip():
                translated_parts.append(part)
                continue
            translated = self._translate_offline_core(part.strip(), src_lang, tgt_lang) or part.strip()
            translated_parts.append(translated)
        combined = "".join(translated_parts).strip()
        if tgt_lang == "en":
            combined = re.sub(r"\s+", " ", combined)
            combined = re.sub(r"\s+([,.;:!?])", r"\1", combined)
        return combined or None

    def _map_punctuation(self, token: str, tgt_lang: str) -> str:
        if tgt_lang == "en":
            mapping = {
                "，": ", ",
                "。": ". ",
                "！": "! ",
                "？": "? ",
                "；": "; ",
                "：": ": ",
                "\n": " ",
            }
            return mapping.get(token, token)
        if tgt_lang == "zh":
            mapping = {
                ",": "，",
                ".": "。",
                "!": "！",
                "?": "？",
                ";": "；",
                ":": "：",
            }
            return mapping.get(token, token)
        return token

    def _direct_translate(self, text: str, src_lang: str, tgt_lang: str) -> str | None:
        languages = {lang.code: lang for lang in argostranslate.translate.get_installed_languages()}
        src = languages.get(src_lang)
        tgt = languages.get(tgt_lang)
        if not src or not tgt:
            return None
        translation = src.get_translation(tgt)
        if translation is None:
            return None
        return translation.translate(text)
