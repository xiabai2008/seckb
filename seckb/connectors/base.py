from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class RawItem:
    source_id: str
    title: str
    content: str
    asset_type: str = "post"
    url: str | None = None
    published_at: str | None = None
    extra: dict = field(default_factory=dict)


class Connector(Protocol):
    name: str

    def fetch(self, cursor: str | None) -> tuple[list[RawItem], str | None]: ...
