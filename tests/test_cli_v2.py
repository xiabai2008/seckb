from pathlib import Path

from typer.testing import CliRunner

from seckb.cli import app

runner = CliRunner()


def write_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "settings.yaml").write_text(
        f"kb_root: {(tmp_path / 'KB').as_posix()}\n", encoding="utf-8"
    )
    return cfg


def test_help_lists_new_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("collect", "enrich", "embed", "index", "sources", "daemon"):
        assert command in result.output


def test_enrich_without_api_key_exits_1(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cfg = write_config(tmp_path)
    result = runner.invoke(app, ["--config", str(cfg), "enrich"])
    assert result.exit_code == 1
    assert "API Key" in result.output


def test_sources_command_lists_configured_sources(tmp_path: Path):
    cfg = write_config(tmp_path)
    (cfg / "sources.yaml").write_text(
        "sources:\n  rss:\n    type: rss\n    feeds: [https://e.com/f]\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["--config", str(cfg), "sources"])
    assert result.exit_code == 0
    assert "rss" in result.output
