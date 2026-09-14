from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = REPO_ROOT / "config"
DEFAULT_KB_ROOT = Path("D:/SecurityKB")


@dataclass
class Settings:
    kb_root: Path
    config_dir: Path = DEFAULT_CONFIG_DIR
    taxonomy: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    enrich: dict = field(default_factory=dict)
    schedule: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.kb_root / "meta" / "catalog.db"


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_settings(config_dir: Path | None = None) -> Settings:
    env_dir = os.environ.get("SECKB_CONFIG")
    cfg_dir = Path(env_dir) if env_dir else Path(config_dir) if config_dir else DEFAULT_CONFIG_DIR
    kb_root = Path(os.environ.get("SECKB_ROOT", DEFAULT_KB_ROOT))

    data = _read_yaml(cfg_dir / "settings.yaml")
    if data.get("kb_root"):
        kb_root = Path(data["kb_root"])

    return Settings(
        kb_root=kb_root,
        config_dir=cfg_dir,
        taxonomy=_read_yaml(cfg_dir / "taxonomy.yaml"),
        sources=_read_yaml(cfg_dir / "sources.yaml").get("sources", {}),
        enrich=_read_yaml(cfg_dir / "enrich.yaml"),
        schedule=_read_yaml(cfg_dir / "schedule.yaml"),
    )
