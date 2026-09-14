from seckb.db.connection import init_db
from seckb.models import Asset, ChunkDraft, SnippetDraft


def test_init_db_creates_dirs_and_tables(kb):
    assert kb.settings.db_path.exists()
    names = {
        row["name"]
        for row in kb.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for expected in (
        "assets",
        "chunks",
        "snippets",
        "entities",
        "asset_entities",
        "books",
        "posts",
        "chunks_fts",
    ):
        assert expected in names


def test_migrate_is_idempotent(kb):
    from seckb.db.migrate import migrate

    assert kb.conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert migrate(kb.conn) == 2


def test_foreign_key_cascade(kb):
    conn = kb.conn
    conn.execute(
        "INSERT INTO assets(type, title, sha256, format, imported_at) VALUES('post','t','abc','markdown','now')"
    )
    asset_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO chunks(asset_id, seq, token_count, content_md) VALUES(?, 0, 5, 'hello')",
        (asset_id,),
    )
    conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
    count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    assert count == 0


def test_models_defaults():
    asset = Asset(type="post", title="t", sha256="x", format="markdown")
    assert asset.tags == []
    assert asset.status == "ok"
    assert asset.lang == "zh"
    assert ChunkDraft(seq=0, heading_path="", content="a", token_count=1).seq == 0
    assert SnippetDraft(kind="command", lang="bash", content="ls").tool is None


def test_init_db_twice_is_safe(kb):
    conn2 = init_db(kb.root)
    assert conn2.execute("PRAGMA user_version").fetchone()[0] == 2
    conn2.close()
