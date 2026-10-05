"""Global search service (MOD-09 / T-211).

Combines the repository's backend-filtered candidates with relevance scoring,
filtering and pagination. Scoring rewards name matches most heavily, then tags,
then description/owner mentions.
"""
from __future__ import annotations

import re
from typing import List

from .models import CatalogRecord, SearchHit, SearchQuery, SearchResult

_TOKEN_RE = re.compile(r"[\s_\-]+|(?<=[a-z])(?=[A-Z])")


def tokenize(term: str | None) -> List[str]:
    if not term:
        return []
    return [t.lower() for t in _TOKEN_RE.split(term) if t]


def _matched_fields(record: CatalogRecord, tokens: List[str]) -> List[str]:
    matched: List[str] = []
    for tok in tokens:
        if record.name and tok and (tok == record.name.lower() or tok in record.name.lower()):
            matched.append("name")
        if record.description and tok in record.description.lower():
            matched.append("description")
        if any(tok in (t or "").lower() for t in record.tags):
            matched.append("tag")
        if record.owner and tok in record.owner.lower():
            matched.append("owner")
    return list(dict.fromkeys(matched))


def _score(record: CatalogRecord, tokens: List[str]) -> float:
    score = 0.0
    for tok in tokens:
        if not tok:
            continue
        if record.name:
            nl = record.name.lower()
            if nl == tok:
                score += 10
            elif nl.startswith(tok):
                score += 6
            elif tok in nl:
                score += 4
        if record.description and tok in record.description.lower():
            score += 2
        if any(tok in (t or "").lower() for t in record.tags):
            score += 3
        if record.owner and tok in record.owner.lower():
            score += 1
    return score


class SearchService:
    def __init__(self, repository) -> None:
        self._repo = repository

    def search(self, query: SearchQuery) -> SearchResult:
        tokens = tokenize(query.term)
        records = self._repo.search(
            term=query.term,
            datasource_id=query.datasource_id,
            type=query.type,
            tags=query.tags or None,
            owner=query.owner,
            sensitive_only=query.sensitive_only,
            grade_min=query.grade_min,
        )
        scored = []
        for r in records:
            sc = _score(r, tokens)
            matched = _matched_fields(r, tokens) if tokens else []
            scored.append((sc, r, matched))

        # Highest relevance first; stable tie-break by fqn.
        scored.sort(key=lambda x: (-x[0], x[1].fqn))
        total = len(scored)
        page = scored[query.offset : query.offset + query.limit]
        items = [
            SearchHit(
                entity_type=r.entity_type,
                fqn=r.fqn,
                name=r.name,
                datasource_id=r.datasource_id,
                schema=r.schema,
                parent_fqn=r.parent_fqn,
                description=r.description,
                tags=list(r.tags),
                owner=r.owner,
                is_pii=r.is_pii,
                score=sc,
                matched_in=matched,
                id=r.id,
            )
            for sc, r, matched in page
        ]
        return SearchResult(items=items, total=total, limit=query.limit, offset=query.offset)
