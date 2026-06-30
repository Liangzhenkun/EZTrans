from eztrans.services.importers import parse_cedict_lines


def test_parse_cedict_lines_builds_bidirectional_entries():
    zh_to_en, en_to_zh = parse_cedict_lines(
        [
            "你好 你好 [ni3 hao3] /hello/hi/",
            "谢谢 谢谢 [xie4 xie5] /thanks/thank you/",
        ]
    )
    assert zh_to_en
    assert en_to_zh
    assert zh_to_en[0].headword == "你好"
    assert "hello" in zh_to_en[0].gloss
    assert any(entry.headword == "thank you" for entry in en_to_zh)

