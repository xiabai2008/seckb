from seckb.utils.tokens import estimate_tokens


def test_empty():
    assert estimate_tokens("") == 0


def test_english_words():
    assert estimate_tokens("hello world") == 2


def test_cjk_chars_count_individually():
    assert estimate_tokens("你好世界") == 4


def test_mixed_text_is_reasonable():
    text = "使用 sqlmap 进行 SQL 注入测试"
    assert 8 <= estimate_tokens(text) <= 16
