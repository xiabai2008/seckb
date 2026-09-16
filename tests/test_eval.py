from pathlib import Path

from seckb.eval import EvalCase, load_cases, run_eval
from seckb.pipeline.importer import import_file
from seckb.retrieval import HybridRetriever


def test_load_cases(tmp_path: Path):
    path = tmp_path / "cases.yaml"
    path.write_text("- query: fastjson\n  expect_any: [fastjson]\n", encoding="utf-8")
    cases = load_cases(path)
    assert cases == [EvalCase(query="fastjson", expect_any=["fastjson"], type=None)]


def test_run_eval_counts_hits(kb, tmp_path: Path):
    src = tmp_path / "a.md"
    src.write_text("# fastjson 反序列化\n\n利用记录。", encoding="utf-8")
    import_file(kb.conn, kb.settings, src)
    retriever = HybridRetriever(kb.conn, kb.settings)
    cases = [
        EvalCase(query="fastjson", expect_any=["fastjson"]),
        EvalCase(query="fastjson", expect_any=["绝不匹配xyz"]),
    ]
    report = run_eval(retriever, cases)
    assert report.total == 2
    assert report.passed == 1
    assert report.details[0].passed is True
    assert report.details[1].passed is False
    assert report.hit_rate == 0.5


def test_default_golden_queries_file_is_valid():
    from seckb.eval import DEFAULT_CASES_PATH

    cases = load_cases(DEFAULT_CASES_PATH)
    assert len(cases) >= 10
    for case in cases:
        assert case.query and case.expect_any
