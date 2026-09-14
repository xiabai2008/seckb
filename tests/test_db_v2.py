import sqlite3

import pytest


def test_user_version_is_2(kb):
    assert kb.conn.execute("PRAGMA user_version").fetchone()[0] == 2


def test_new_tables_exist(kb):
    names = {
        row["name"]
        for row in kb.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for expected in {"sources", "runs", "jobs", "cards", "repos", "cves"}:
        assert expected in names


def test_assets_has_source_id(kb):
    columns = {row["name"] for row in kb.conn.execute("PRAGMA table_info(assets)")}
    assert "source_id" in columns


def test_source_id_unique_per_source(kb):
    kb.conn.execute(
        "INSERT INTO assets(type, title, sha256, format, imported_at, source, source_id)"
        " VALUES('post','a','s1','markdown','now','rss','e1')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        kb.conn.execute(
            "INSERT INTO assets(type, title, sha256, format, imported_at, source, source_id)"
            " VALUES('post','b','s2','markdown','now','rss','e1')"
        )
    kb.conn.execute(
        "INSERT INTO assets(type, title, sha256, format, imported_at, source, source_id)"
        " VALUES('post','c','s3','markdown','now','manual',NULL)"
    )
    kb.conn.execute(
        "INSERT INTO assets(type, title, sha256, format, imported_at, source, source_id)"
        " VALUES('post','d','s4','markdown','now','manual',NULL)"
    )
