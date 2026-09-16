from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from seckb.config import REPO_ROOT
from seckb.retrieval import HybridRetriever

DEFAULT_CASES_PATH = REPO_ROOT / "tests" / "eval" / "golden_queries.yaml"


@dataclass
class EvalCase:
    query: str
    expect_any: list[str]
    type: str | None = None


@dataclass
class EvalDetail:
    query: str
    passed: bool
    top_titles: list[str]
    degraded: list[str]


@dataclass
class EvalReport:
    total: int = 0
    passed: int = 0
    details: list[EvalDetail] = field(default_factory=list)

    @property
    def hit_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


def load_cases(path: Path) -> list[EvalCase]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    return [
        EvalCase(
            query=str(entry["query"]),
            expect_any=[str(item) for item in entry.get("expect_any") or []],
            type=entry.get("type"),
        )
        for entry in data
    ]


def _matches(case: EvalCase, title: str, tags: list[str]) -> bool:
    haystack = f"{title} {' '.join(tags)}".lower()
    return any(expectation.lower() in haystack for expectation in case.expect_any)


def run_eval(retriever: HybridRetriever, cases: list[EvalCase], *, top: int = 5) -> EvalReport:
    report = EvalReport(total=len(cases))
    for case in cases:
        response = retriever.search(case.query, asset_type=case.type, limit=top)
        passed = any(_matches(case, item.title, item.tags) for item in response.results)
        if passed:
            report.passed += 1
        report.details.append(
            EvalDetail(
                query=case.query,
                passed=passed,
                top_titles=[item.title for item in response.results],
                degraded=response.degraded,
            )
        )
    return report
