import sqlite3
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


def import_post(tmp_path: Path, cfg: Path, body: str) -> None:
    src = tmp_path / "post.md"
    src.write_text(body, encoding="utf-8")
    result = runner.invoke(app, ["--config", str(cfg), "import", str(src)])
    assert result.exit_code == 0


def test_cli_search_hybrid_output(tmp_path: Path):
    cfg = write_config(tmp_path)
    runner.invoke(app, ["--config", str(cfg), "init"])
    import_post(tmp_path, cfg, "# 永恒之蓝复现\n\nMS17-010 利用记录。")
    result = runner.invoke(app, ["--config", str(cfg), "search", "永恒之蓝"])
    assert result.exit_code == 0
    assert "永恒之蓝" in result.output
    assert "fts" in result.output


def test_cli_card_and_get(tmp_path: Path):
    cfg = write_config(tmp_path)
    runner.invoke(app, ["--config", str(cfg), "init"])
    import_post(tmp_path, cfg, "# 提权笔记\n\nLinux 提权常见手法。")
    db = sqlite3.connect(str(tmp_path / "KB" / "meta" / "catalog.db"))
    db.execute(
        "INSERT INTO cards(asset_id, summary, key_takeaways, card_json, model, generated_at)"
        " VALUES(1, '提权摘要', '[\"要点\"]', '{}', 'fake', 'now')"
    )
    db.commit()
    db.close()
    result = runner.invoke(app, ["--config", str(cfg), "card", "1"])
    assert result.exit_code == 0
    assert "提权摘要" in result.output
    result = runner.invoke(app, ["--config", str(cfg), "get", "1", "--max-tokens", "10000"])
    assert result.exit_code == 0
    assert "提权" in result.output


def test_cli_get_missing_exits_1(tmp_path: Path):
    cfg = write_config(tmp_path)
    runner.invoke(app, ["--config", str(cfg), "init"])
    result = runner.invoke(app, ["--config", str(cfg), "get", "999"])
    assert result.exit_code == 1


def test_cli_snippets(tmp_path: Path):
    cfg = write_config(tmp_path)
    runner.invoke(app, ["--config", str(cfg), "init"])
    import_post(
        tmp_path,
        cfg,
        "# 扫描笔记\n\n```bash\nnmap -sV -p445 10.0.0.1\n```\n",
    )
    result = runner.invoke(app, ["--config", str(cfg), "snippets", "--kind", "oneliner"])
    assert result.exit_code == 0
    assert "nmap" in result.output
