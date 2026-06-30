from __future__ import annotations

import sqlite3
import threading
from csv import DictWriter
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import json

from ..models import DictionaryEntry, ExampleSentence, HistoryRecord, ResourceStatus
from ..utils import extract_search_terms, normalize_text


class DictionaryDatabase:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.initialize()

    @contextmanager
    def connect(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path, timeout=60)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS dictionary_entries (
                    id INTEGER PRIMARY KEY,
                    src_lang TEXT NOT NULL,
                    tgt_lang TEXT NOT NULL,
                    headword TEXT NOT NULL,
                    normalized_headword TEXT NOT NULL,
                    reading TEXT DEFAULT '',
                    pos TEXT DEFAULT '',
                    gloss TEXT NOT NULL,
                    source TEXT NOT NULL,
                    weight REAL DEFAULT 1.0
                );
                CREATE INDEX IF NOT EXISTS idx_dictionary_pair
                    ON dictionary_entries(src_lang, tgt_lang, normalized_headword);
                CREATE VIRTUAL TABLE IF NOT EXISTS dictionary_entries_fts
                    USING fts5(headword, normalized_headword, gloss, content='dictionary_entries', content_rowid='id');
                CREATE TABLE IF NOT EXISTS example_sentences (
                    id INTEGER PRIMARY KEY,
                    src_lang TEXT NOT NULL,
                    tgt_lang TEXT NOT NULL,
                    source_text TEXT NOT NULL,
                    target_text TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    quality_score REAL DEFAULT 0.5
                );
                CREATE INDEX IF NOT EXISTS idx_examples_pair
                    ON example_sentences(src_lang, tgt_lang);
                CREATE TABLE IF NOT EXISTS resource_versions (
                    key TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    installed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS translation_history (
                    id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    input_text TEXT NOT NULL,
                    normalized_input TEXT NOT NULL DEFAULT '',
                    src_lang TEXT NOT NULL,
                    tgt_lang TEXT NOT NULL,
                    detected_lang TEXT NOT NULL,
                    translated_text TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    provider_kind TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_history_created_at
                    ON translation_history(created_at DESC);
                """
            )
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(translation_history)").fetchall()
            }
            if "normalized_input" not in columns:
                conn.execute(
                    "ALTER TABLE translation_history ADD COLUMN normalized_input TEXT NOT NULL DEFAULT ''"
                )
            conn.execute(
                """
                UPDATE translation_history
                SET normalized_input = lower(trim(input_text))
                WHERE normalized_input = ''
                """
            )
            self._cleanup_history_duplicates(conn)

    def import_dictionary_entries(
        self,
        entries: list[DictionaryEntry],
        resource_key: str,
        resource_version: str,
    ) -> int:
        if not entries:
            return 0
        with self.connect() as conn:
            src_lang = entries[0].src_lang
            tgt_lang = entries[0].tgt_lang
            existing_ids = conn.execute(
                """
                SELECT id FROM dictionary_entries
                WHERE src_lang = ? AND tgt_lang = ? AND source = ?
                """,
                (src_lang, tgt_lang, entries[0].source),
            ).fetchall()
            for row in existing_ids:
                conn.execute("DELETE FROM dictionary_entries_fts WHERE rowid = ?", (row["id"],))
            conn.execute(
                "DELETE FROM dictionary_entries WHERE src_lang = ? AND tgt_lang = ? AND source = ?",
                (src_lang, tgt_lang, entries[0].source),
            )
            conn.executemany(
                """
                INSERT INTO dictionary_entries (
                    src_lang, tgt_lang, headword, normalized_headword, reading, pos, gloss, source, weight
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        entry.src_lang,
                        entry.tgt_lang,
                        entry.headword,
                        normalize_text(entry.headword),
                        entry.reading,
                        entry.pos,
                        entry.gloss,
                        entry.source,
                        entry.score or 1.0,
                    )
                    for entry in entries
                ],
            )
            conn.execute(
                """
                INSERT INTO dictionary_entries_fts(rowid, headword, normalized_headword, gloss)
                SELECT id, headword, normalized_headword, gloss
                FROM dictionary_entries
                WHERE src_lang = ? AND tgt_lang = ? AND source = ?
                """,
                (src_lang, tgt_lang, entries[0].source),
            )
            conn.execute(
                """
                INSERT INTO resource_versions(key, version, installed_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE
                SET version = excluded.version, installed_at = excluded.installed_at
                """,
                (resource_key, resource_version, datetime.utcnow().isoformat()),
            )
        return len(entries)

    def import_examples(
        self,
        examples: list[ExampleSentence],
        resource_key: str,
        resource_version: str,
    ) -> int:
        if not examples:
            return 0
        with self.connect() as conn:
            conn.execute("DELETE FROM example_sentences WHERE source_name = ?", (examples[0].source_name,))
            conn.executemany(
                """
                INSERT INTO example_sentences (
                    src_lang, tgt_lang, source_text, target_text, source_name, quality_score
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row.src_lang,
                        row.tgt_lang,
                        row.source_text,
                        row.target_text,
                        row.source_name,
                        row.quality_score,
                    )
                    for row in examples
                ],
            )
            conn.execute(
                """
                INSERT INTO resource_versions(key, version, installed_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE
                SET version = excluded.version, installed_at = excluded.installed_at
                """,
                (resource_key, resource_version, datetime.utcnow().isoformat()),
            )
        return len(examples)

    def search_entries(self, src_lang: str, tgt_lang: str, query: str, limit: int = 6) -> list[DictionaryEntry]:
        normalized = normalize_text(query)
        if not normalized:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT headword, gloss, reading, pos, source, weight,
                       CASE
                           WHEN normalized_headword = ? THEN 3
                           WHEN normalized_headword LIKE ? THEN 2
                           ELSE 1
                       END AS match_rank
                FROM dictionary_entries
                WHERE src_lang = ? AND tgt_lang = ?
                  AND (
                    normalized_headword = ?
                    OR normalized_headword LIKE ?
                    OR gloss LIKE ?
                  )
                ORDER BY match_rank DESC, weight DESC, LENGTH(headword) ASC
                LIMIT ?
                """,
                (
                    normalized,
                    f"{normalized}%",
                    src_lang,
                    tgt_lang,
                    normalized,
                    f"{normalized}%",
                    f"%{query.strip()}%",
                    limit,
                ),
            ).fetchall()
        return [
            DictionaryEntry(
                src_lang=src_lang,
                tgt_lang=tgt_lang,
                headword=row["headword"],
                gloss=row["gloss"],
                reading=row["reading"],
                pos=row["pos"],
                source=row["source"],
                score=float(row["weight"]),
            )
            for row in rows
        ]

    def search_examples(self, src_lang: str, tgt_lang: str, query: str, limit: int = 2) -> list[ExampleSentence]:
        cleaned = query.strip()
        if not cleaned:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT src_lang, tgt_lang, source_text, target_text, source_name, quality_score
                FROM example_sentences
                WHERE src_lang = ? AND tgt_lang = ?
                  AND source_text LIKE ?
                ORDER BY quality_score DESC, LENGTH(source_text) ASC
                LIMIT ?
                """,
                (src_lang, tgt_lang, f"%{cleaned}%", limit),
            ).fetchall()
            if not rows:
                terms = extract_search_terms(cleaned)
                for term in terms:
                    rows = conn.execute(
                        """
                        SELECT src_lang, tgt_lang, source_text, target_text, source_name, quality_score
                        FROM example_sentences
                        WHERE src_lang = ? AND tgt_lang = ?
                          AND source_text LIKE ?
                        ORDER BY quality_score DESC, LENGTH(source_text) ASC
                        LIMIT ?
                        """,
                        (src_lang, tgt_lang, f"%{term}%", limit),
                    ).fetchall()
                    if rows:
                        break
        return [
            ExampleSentence(
                src_lang=row["src_lang"],
                tgt_lang=row["tgt_lang"],
                source_text=row["source_text"],
                target_text=row["target_text"],
                source_name=row["source_name"],
                quality_score=float(row["quality_score"]),
            )
            for row in rows
        ]

    def get_resource_status(self, key: str) -> ResourceStatus | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT key, version, installed_at FROM resource_versions WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return ResourceStatus(
            key=row["key"],
            version=row["version"],
            installed_at=datetime.fromisoformat(row["installed_at"]),
        )

    def set_resource_status(self, key: str, version: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO resource_versions(key, version, installed_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE
                SET version = excluded.version, installed_at = excluded.installed_at
                """,
                (key, version, datetime.utcnow().isoformat()),
            )

    def add_history_record(self, record: HistoryRecord) -> None:
        with self.connect() as conn:
            normalized_input = normalize_text(record.input_text)
            rows = conn.execute(
                """
                SELECT id FROM translation_history
                WHERE detected_lang = ? AND tgt_lang = ? AND normalized_input = ?
                ORDER BY created_at DESC
                """,
                (record.detected_lang, record.tgt_lang, normalized_input),
            ).fetchall()
            if rows:
                keep_id = rows[0]["id"]
                conn.execute(
                    """
                    UPDATE translation_history
                    SET created_at = ?, input_text = ?, normalized_input = ?, src_lang = ?,
                        tgt_lang = ?, detected_lang = ?, translated_text = ?, provider_id = ?, provider_kind = ?
                    WHERE id = ?
                    """,
                    (
                        record.created_at,
                        record.input_text,
                        normalized_input,
                        record.src_lang,
                        record.tgt_lang,
                        record.detected_lang,
                        record.translated_text,
                        record.provider_id,
                        record.provider_kind,
                        keep_id,
                    ),
                )
                if len(rows) > 1:
                    conn.executemany(
                        "DELETE FROM translation_history WHERE id = ?",
                        [(row["id"],) for row in rows[1:]],
                    )
                return
            conn.execute(
                """
                INSERT INTO translation_history (
                    created_at, input_text, normalized_input, src_lang, tgt_lang, detected_lang,
                    translated_text, provider_id, provider_kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.created_at,
                    record.input_text,
                    normalized_input,
                    record.src_lang,
                    record.tgt_lang,
                    record.detected_lang,
                    record.translated_text,
                    record.provider_id,
                    record.provider_kind,
                ),
            )

    def list_history(self, limit: int = 200) -> list[HistoryRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT created_at, input_text, src_lang, tgt_lang, detected_lang,
                       translated_text, provider_id, provider_kind
                FROM translation_history
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            HistoryRecord(
                created_at=row["created_at"],
                input_text=row["input_text"],
                src_lang=row["src_lang"],
                tgt_lang=row["tgt_lang"],
                detected_lang=row["detected_lang"],
                translated_text=row["translated_text"],
                provider_id=row["provider_id"],
                provider_kind=row["provider_kind"],
            )
            for row in rows
        ]

    def export_history(self, file_path: Path) -> None:
        records = self.list_history(limit=5000)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if file_path.suffix.lower() == ".json":
            file_path.write_text(
                json.dumps([asdict(record) for record in records], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return
        with file_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = DictWriter(
                handle,
                fieldnames=[
                    "created_at",
                    "input_text",
                    "src_lang",
                    "tgt_lang",
                    "detected_lang",
                    "translated_text",
                    "provider_id",
                    "provider_kind",
                ],
            )
            writer.writeheader()
            for record in records:
                writer.writerow(asdict(record))

    def _cleanup_history_duplicates(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """
            SELECT id, detected_lang, tgt_lang, normalized_input, created_at
            FROM translation_history
            ORDER BY created_at DESC
            """
        ).fetchall()
        seen: set[tuple[str, str, str]] = set()
        to_delete: list[tuple[int]] = []
        for row in rows:
            key = (row["detected_lang"], row["tgt_lang"], row["normalized_input"])
            if key in seen:
                to_delete.append((row["id"],))
            else:
                seen.add(key)
        if to_delete:
            conn.executemany("DELETE FROM translation_history WHERE id = ?", to_delete)
