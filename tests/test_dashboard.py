from pathlib import Path

from seckb import __version__
from seckb.dashboard import build_stats, list_assets, load_dashboard_html
from seckb.pipeline.importer import import_file


def test_dashboard_html_injects_package_version():
    html = load_dashboard_html()
    assert __version__ in html
    assert "__VERSION__" not in html


def make_asset(kb, tmp_path: Path, name: str, title: str, body: str, **kwargs) -> int:
    src = tmp_path / name
    src.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    return import_file(kb.conn, kb.settings, src, **kwargs).asset_id


def test_build_stats_counts(kb, tmp_path: Path):
    asset_id = make_asset(kb, tmp_path, "a.md", "永恒之蓝复现", "MS17-010 利用记录。")
    kb.conn.execute(
        "INSERT INTO cards(asset_id, summary, key_takeaways, card_json, model, generated_at)"
        " VALUES(?, '摘要', '[]', '{}', 'fake', 'now')",
        (asset_id,),
    )
    kb.conn.commit()
    stats = build_stats(kb.conn)
    assert stats["totals"]["assets"] == 1
    assert stats["totals"]["cards"] == 1
    assert stats["totals"]["chunks"] >= 1
    assert any(item["name"] == "post" and item["count"] == 1 for item in stats["by_type"])
    assert stats["growth"], "近 30 天增长序列不应为空"
    assert stats["recent"][0]["id"] == asset_id


def test_list_assets_filters_and_pagination(kb, tmp_path: Path):
    for index in range(3):
        make_asset(
            kb,
            tmp_path,
            f"p{index}.md",
            f"帖子 {index}",
            f"正文内容 {index}。",
        )
    make_asset(
        kb,
        tmp_path,
        "cve.md",
        "CVE-2021-44228",
        "Log4Shell 记录。",
        asset_type="cve",
        source="nvd",
        source_id="CVE-2021-44228",
    )

    page_one = list_assets(kb.conn, page=1, page_size=2)
    assert page_one["total"] == 4
    assert len(page_one["items"]) == 2
    page_two = list_assets(kb.conn, page=2, page_size=2)
    assert len(page_two["items"]) == 2
    assert {item["id"] for item in page_one["items"]}.isdisjoint(
        {item["id"] for item in page_two["items"]}
    )

    cves = list_assets(kb.conn, asset_type="cve")
    assert cves["total"] == 1
    assert cves["items"][0]["title"] == "CVE-2021-44228"

    by_source = list_assets(kb.conn, source="nvd")
    assert by_source["total"] == 1

    by_query = list_assets(kb.conn, q="帖子")
    assert by_query["total"] == 3

    page_size_capped = list_assets(kb.conn, page_size=9999)
    assert page_size_capped["page_size"] == 200


def test_list_assets_reports_card_flag(kb, tmp_path: Path):
    asset_id = make_asset(kb, tmp_path, "a.md", "有卡片", "正文。")
    before = list_assets(kb.conn, q="有卡片")["items"][0]
    assert before["has_card"] is False
    kb.conn.execute(
        "INSERT INTO cards(asset_id, summary, key_takeaways, card_json, model, generated_at)"
        " VALUES(?, '摘要', '[]', '{}', 'fake', 'now')",
        (asset_id,),
    )
    kb.conn.commit()
    after = list_assets(kb.conn, q="有卡片")["items"][0]
    assert after["has_card"] is True
    assert after["tags"] == []
