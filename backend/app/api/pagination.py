"""Page parameters shared by every listing endpoint."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

from fastapi import Query

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500


@dataclass(frozen=True)
class PageParams:
    limit: int
    offset: int

    def page(self, items: List[Any], total: int) -> dict:
        return {"items": items, "total": total, "limit": self.limit, "offset": self.offset}


def page_params(
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Page size."),
    offset: int = Query(default=0, ge=0, description="Rows to skip."),
) -> PageParams:
    return PageParams(limit=limit, offset=offset)
