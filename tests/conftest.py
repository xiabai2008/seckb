from __future__ import annotations

from pathlib import Path

import pytest

from seckb.config import Settings
from seckb.db.connection import init_db


class KB:
    root: Path
    settings: Settings
    conn: object


@pytest.fixture
def kb(tmp_path: Path):
    instance = KB()
    instance.root = tmp_path / "SecurityKB"
    instance.settings = Settings(
        kb_root=instance.root,
        taxonomy={
            "directions": {
                "web-security": ["sql注入", "xss", "web"],
                "pentest": ["渗透", "提权"],
            },
            "tools": ["nmap", "sqlmap", "nuclei"],
        },
    )
    instance.conn = init_db(instance.root)
    yield instance
    instance.conn.close()
