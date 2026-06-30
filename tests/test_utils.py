from eztrans.utils import looks_like_single_term


def test_looks_like_single_term_accepts_short_phrase():
    assert looks_like_single_term("take off")
    assert looks_like_single_term("马上")


def test_looks_like_single_term_rejects_full_sentence():
    assert not looks_like_single_term("今天过得怎么样？我昨天吃了炖排骨，非常香。")
    assert not looks_like_single_term("How was your day? I ate ribs yesterday.")
