from __future__ import annotations

import json
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from seckb.config import Settings
from seckb.indexer import fts
from seckb.pipeline import rules
from seckb.pipeline.chunker import chunk_markdown
from seckb.pipeline.dedupe import find_by_sha256, find_near_duplicate
from seckb.pipeline.normalize import normalize_to_markdown
from seckb.utils.hashing import sha256_file, slugify
from seckb.utils.simhash import simhash64, to_signed64

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_H1_RE = re.compile(r"^#\s+(.+?)\s*$")


@dataclass
class ImportReport:
    status: str
    asset_id: int | None = None
    path: str | None = None


def _first_h1(markdown: str) -> str:
    for line in markdown.splitlines():
        match = _H1_RE.match(line)
        if match:
            return match.group(1).strip().rstrip("#").strip()
    return ""


def detect_lang(text: str) -> str:
    if not text:
        return "en"
    cjk = len(_CJK_RE.findall(text))
    return "zh" if cjk / max(len(text), 1) > 0.05 else "en"


def guess_direction(title: str, text: str, directions: dict[str, list[str]]) -> str:
    sample = (title + "\n" + text[:2000]).lower()
    best, best_score = "misc", 0
    for direction, keywords in directions.items():
        score = sum(1 for keyword in keywords if keyword.lower() in sample)
        if score > best_score:
            best, best_score = direction, score
    return best


def _link_entity(conn: sqlite3.Connection, asset_id: int, kind: str, name: str) -> None:
    canonical = name.lower()
    row = conn.execute(
        "SELECT id FROM entities WHERE kind = ? AND canonical = ?", (kind, canonical)
    ).fetchone()
    if row:
        entity_id = row["id"]
    else:
        cursor = conn.execute(
            "INSERT INTO entities(kind, name, canonical) VALUES(?,?,?)", (kind, name, canonical)
        )
        entity_id = cursor.lastrowid
    conn.execute(
        "INSERT OR IGNORE INTO asset_entities(asset_id, entity_id) VALUES(?,?)",
        (asset_id, entity_id),
    )


def import_file(
    conn: sqlite3.Connection,
    settings: Settings,
    src: Path,
    *,
    asset_type: str | None = None,
) -> ImportReport:
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(src)

    orig_size = src.stat().st_size
    sha = sha256_file(src)
    existing = find_by_sha256(conn, sha)
    if existing:
        return ImportReport("duplicated", existing, None)

    tmp_dir = settings.kb_root / "meta" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{sha[:8]}-{slugify(src.stem)}"

    result = normalize_to_markdown(src, out_dir=tmp_dir, stem=stem)
    if result.needs_ocr:
        return ImportReport("needs_ocr", None, str(src))

    near = find_near_duplicate(conn, result.markdown)
    if near is not None:
        return ImportReport("duplicated", near, None)

    kind = asset_type or ("book" if result.source_type in {"pdf", "epub"} else "post")
    title = result.title
    if result.source_type == "markdown":
        title = _first_h1(result.markdown) or result.title
    direction = guess_direction(
        title, result.markdown, settings.taxonomy.get("directions", {})
    )
    lang = detect_lang(result.markdown)

    rel_dir = Path("books") / direction if kind == "book" else Path("posts") / lang
    out_dir = settings.kb_root / rel_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    tmp_images = tmp_dir / f"{stem}.assets"
    if tmp_images.is_dir():
        shutil.move(str(tmp_images), str(out_dir / f"{stem}.assets"))

    md_path = out_dir / f"{stem}.md"
    md_path.write_text(result.markdown, encoding="utf-8")
    md_rel = md_path.relative_to(settings.kb_root).as_posix()

    if result.source_type == "markdown":
        orig_rel = md_rel
        src.unlink()
    else:
        orig_path = out_dir / f"{stem}{src.suffix.lower()}"
        shutil.move(str(src), str(orig_path))
        orig_rel = orig_path.relative_to(settings.kb_root).as_posix()

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cursor = conn.execute(
        """
        INSERT INTO assets(type, title, lang, source, source_url, path, md_path,
                           sha256, simhash, size, format, imported_at, tags, category, status)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            kind,
            title,
            lang,
            "manual",
            None,
            orig_rel,
            md_rel,
            sha,
            to_signed64(simhash64(result.markdown)),
            orig_size,
            result.source_type,
            now,
            "[]",
            direction,
            "ok",
        ),
    )
    asset_id = cursor.lastrowid

    for draft in chunk_markdown(result.markdown):
        conn.execute(
            "INSERT INTO chunks(asset_id, seq, heading_path, token_count, content_md) VALUES(?,?,?,?,?)",
            (asset_id, draft.seq, draft.heading_path, draft.token_count, draft.content),
        )

    for snippet in rules.extract_snippets(result.markdown):
        conn.execute(
            "INSERT INTO snippets(asset_id, kind, lang, tool, content) VALUES(?,?,?,?,?)",
            (asset_id, snippet.kind, snippet.lang, snippet.tool, snippet.content),
        )

    for cve in rules.extract_cves(result.markdown):
        _link_entity(conn, asset_id, "cve", cve)
    for attack_id in rules.extract_attack_ids(result.markdown):
        _link_entity(conn, asset_id, "attack", attack_id)
    for tool in rules.extract_tools(result.markdown, settings.taxonomy.get("tools", [])):
        _link_entity(conn, asset_id, "tool", tool)

    if kind == "book":
        meta = {
            "title": title,
            "sha256": sha,
            "direction": direction,
            "imported_at": now,
        }
        (out_dir / f"{stem}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        conn.execute("INSERT INTO books(asset_id) VALUES(?)", (asset_id,))

    fts.index_asset(conn, asset_id)
    conn.commit()
    return ImportReport("imported", asset_id, md_rel)


def scan_inbox(conn: sqlite3.Connection, settings: Settings) -> list[ImportReport]:
    inbox = settings.kb_root / "inbox"
    reports: list[ImportReport] = []
    for entry in sorted(inbox.iterdir()):
        if entry.is_file():
            reports.append(import_file(conn, settings, entry))
    return reports
