from pathlib import Path

from seckb.config import Settings, load_settings


def test_load_settings_reads_yaml(tmp_path: Path):
    (tmp_path / "settings.yaml").write_text("kb_root: D:/KB-Test\n", encoding="utf-8")
    (tmp_path / "taxonomy.yaml").write_text(
        "directions:\n  web-security: [xss, sql注入]\ntools: [sqlmap, nmap]\n",
        encoding="utf-8",
    )
    settings = load_settings(tmp_path)
    assert settings.kb_root == Path("D:/KB-Test")
    assert "web-security" in settings.taxonomy["directions"]
    assert settings.taxonomy["tools"] == ["sqlmap", "nmap"]


def test_settings_db_path():
    settings = Settings(kb_root=Path("D:/KB"))
    assert settings.db_path == Path("D:/KB/meta/catalog.db")
