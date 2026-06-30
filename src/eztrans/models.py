from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class DictionaryEntry:
    src_lang: str
    tgt_lang: str
    headword: str
    gloss: str
    reading: str = ""
    pos: str = ""
    source: str = ""
    score: float = 0.0


@dataclass(slots=True)
class ExampleSentence:
    src_lang: str
    tgt_lang: str
    source_text: str
    target_text: str
    source_name: str
    quality_score: float = 0.5


@dataclass(slots=True)
class TranslationResult:
    input_text: str
    src_lang: str
    tgt_lang: str
    detected_lang: str
    translated_text: str
    lexical_entries: list[DictionaryEntry] = field(default_factory=list)
    examples: list[ExampleSentence] = field(default_factory=list)
    provider_id: str = "offline"
    provider_kind: str = "offline"
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class HistoryRecord:
    created_at: str
    input_text: str
    src_lang: str
    tgt_lang: str
    detected_lang: str
    translated_text: str
    provider_id: str
    provider_kind: str


@dataclass(slots=True)
class UpdateItem:
    kind: str
    identifier: str
    current_version: str
    latest_version: str
    notes: str = ""


@dataclass(slots=True)
class AppUpdateInfo:
    has_update: bool
    current_version: str
    latest_version: str = ""
    download_url: str = ""
    notes: str = ""


@dataclass(slots=True)
class ResourceStatus:
    key: str
    version: str
    installed_at: datetime | None
