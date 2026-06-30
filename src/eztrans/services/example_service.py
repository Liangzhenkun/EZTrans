from __future__ import annotations

import json
from pathlib import Path

import requests

from ..constants import RESOURCE_KEYS, TATOEBA_LANGUAGE_CODES, TATOEBA_SEARCH_URL
from ..models import ExampleSentence
from .dictionary_db import DictionaryDatabase


class ExampleService:
    def __init__(self, db: DictionaryDatabase, seed_examples_path: Path) -> None:
        self.db = db
        self.seed_examples_path = seed_examples_path

    def bootstrap_seed_examples(self) -> int:
        if self.db.get_resource_status(RESOURCE_KEYS["examples"]) is not None:
            return 0
        data = json.loads(self.seed_examples_path.read_text(encoding="utf-8"))
        examples = [
            ExampleSentence(
                src_lang=row["src_lang"],
                tgt_lang=row["tgt_lang"],
                source_text=row["source_text"],
                target_text=row["target_text"],
                source_name=row["source_name"],
                quality_score=0.7,
            )
            for row in data
        ]
        return self.db.import_examples(examples, RESOURCE_KEYS["examples"], "1")

    def fetch_local_examples(self, src_lang: str, tgt_lang: str, query: str) -> list[ExampleSentence]:
        return self.db.search_examples(src_lang, tgt_lang, query)

    def fetch_online_examples(self, src_lang: str, tgt_lang: str, query: str) -> list[ExampleSentence]:
        src = TATOEBA_LANGUAGE_CODES.get(src_lang)
        tgt = TATOEBA_LANGUAGE_CODES.get(tgt_lang)
        if not src or not tgt:
            return []
        response = requests.get(
            TATOEBA_SEARCH_URL,
            params={"from": src, "to": tgt, "query": query, "page": 1},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("results", [])[:2]
        results: list[ExampleSentence] = []
        for item in items:
            source_text = item.get("text", "").strip()
            translations = item.get("translations", [])
            target_text = ""
            for bucket in translations:
                if not bucket:
                    continue
                candidate = bucket[0].get("text", "").strip()
                if candidate:
                    target_text = candidate
                    break
            if source_text and target_text:
                results.append(
                    ExampleSentence(
                        src_lang=src_lang,
                        tgt_lang=tgt_lang,
                        source_text=source_text,
                        target_text=target_text,
                        source_name="tatoeba",
                        quality_score=0.9,
                    )
                )
        return results

