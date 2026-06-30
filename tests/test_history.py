from eztrans.models import HistoryRecord
from eztrans.services.dictionary_db import DictionaryDatabase


def test_history_export_json_and_csv(tmp_path):
    db = DictionaryDatabase(tmp_path / "history.sqlite3")
    db.add_history_record(
        HistoryRecord(
            created_at="2026-06-30T12:00:00",
            input_text="hello",
            src_lang="en",
            tgt_lang="zh",
            detected_lang="en",
            translated_text="你好",
            provider_id="offline-argos",
            provider_kind="offline",
        )
    )
    csv_path = tmp_path / "history.csv"
    json_path = tmp_path / "history.json"
    db.export_history(csv_path)
    db.export_history(json_path)
    assert csv_path.exists()
    assert json_path.exists()
    assert "hello" in csv_path.read_text(encoding="utf-8-sig")
    assert "你好" in json_path.read_text(encoding="utf-8")


def test_history_deduplicates_same_input_and_target(tmp_path):
    db = DictionaryDatabase(tmp_path / "history.sqlite3")
    first = HistoryRecord(
        created_at="2026-06-30T12:00:00",
        input_text="I need this quickly.",
        src_lang="en",
        tgt_lang="zh",
        detected_lang="en",
        translated_text="我需要这个快。",
        provider_id="offline-argos",
        provider_kind="offline",
    )
    second = HistoryRecord(
        created_at="2026-06-30T12:00:05",
        input_text="I need this quickly.",
        src_lang="en",
        tgt_lang="zh",
        detected_lang="en",
        translated_text="我需要这个快。",
        provider_id="offline-argos",
        provider_kind="offline",
    )
    db.add_history_record(first)
    db.add_history_record(second)
    items = db.list_history(limit=10)
    assert len(items) == 1
    assert items[0].created_at == "2026-06-30T12:00:05"
