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


def test_cli_init_import_search_stats(tmp_path: Path):
    cfg = write_config(tmp_path)
    result = runner.invoke(app, ["--config", str(cfg), "init"])
    assert result.exit_code == 0

    src = tmp_path / "post.md"
    src.write_text("# 永恒之蓝\n\nMS17-010 利用与防护笔记。", encoding="utf-8")
    result = runner.invoke(app, ["--config", str(cfg), "import", str(src)])
    assert result.exit_code == 0
    assert "imported" in result.output

    result = runner.invoke(app, ["--config", str(cfg), "search", "永恒之蓝"])
    assert result.exit_code == 0
    assert "永恒之蓝" in result.output

    result = runner.invoke(app, ["--config", str(cfg), "stats"])
    assert result.exit_code == 0
    assert "post" in result.output
