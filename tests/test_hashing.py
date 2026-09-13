from pathlib import Path

from seckb.utils.hashing import normalize_url, sha256_file, slugify


def test_sha256_file(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    assert sha256_file(f) == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


def test_normalize_url_strips_tracking_and_fragment():
    url = "HTTPS://Example.COM/post/?utm_source=x&id=42#section"
    assert normalize_url(url) == "https://example.com/post?id=42"


def test_slugify_ascii():
    assert slugify("SQLMap Usage Notes!") == "sqlmap-usage-notes"


def test_slugify_chinese_falls_back():
    assert slugify("永恒之蓝利用笔记") == "untitled"
