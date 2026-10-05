"""Overview service: pre-compute + cache rollup (MOD-09 / T-213, FR-11.5).

Per design the rollup is pre-computed and cached (short TTL) rather than
aggregated live on every request. The optional ``change_source`` (a
``ChangeRepository`` from T-204) feeds the recent change trend; when absent the
trend is empty. Quality stats are reported as degraded rather than erroring.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Optional

from .models import CatalogOverview, SENSITIVE_GRADE_THRESHOLD
from .source import CatalogStatsSource


class TtlCache:
    def __init__(self, ttl: float) -> None:
        self._ttl = ttl
        self._value: Optional[CatalogOverview] = None
        self._at: Optional[datetime] = None

    def get(self) -> Optional[CatalogOverview]:
        if self._value is None or self._at is None:
            return None
        if (datetime.now() - self._at).total_seconds() > self._ttl:
            self._value = None
            self._at = None
            return None
        return self._value

    def put(self, value: CatalogOverview) -> CatalogOverview:
        self._value = value
        self._at = datetime.now()
        return value


class OverviewService:
    def __init__(self, catalog_source: CatalogStatsSource, change_source=None,
                 ttl: float = 60.0) -> None:
        self._cat = catalog_source
        self._change = change_source
        self._cache = TtlCache(ttl)

    def _trend(self, since: datetime, until: datetime) -> Dict[str, int]:
        if self._change is None:
            return {}
        rows = self._change.windowed(since, until)
        out: Dict[str, int] = {}
        for e in rows:
            key = e.detected_at.date().isoformat()
            out[key] = out.get(key, 0) + 1
        return dict(sorted(out.items()))

    def get_overview(self, trend_days: int = 30) -> CatalogOverview:
        cached = self._cache.get()
        if cached is not None:
            return cached
        return self.refresh(trend_days=trend_days)

    def refresh(self, trend_days: int = 30) -> CatalogOverview:
        now = datetime.now()
        since = now - timedelta(days=trend_days)
        tables = self._cat.count_tables()
        columns = self._cat.count_columns()
        try:
            datasources = self._cat.count_datasources()
        except Exception:  # noqa: BLE001 - 计数缺失不该让整个总览失败
            datasources = 0
        grades = self._cat.grade_distribution()
        sensitive = self._cat.sensitive_count(SENSITIVE_GRADE_THRESHOLD)
        total_assets = tables + columns
        ratio = round(sensitive / total_assets, 4) if total_assets else 0.0
        quality = self._cat.quality_distribution()
        degraded = ["quality"] if quality is None else []
        trend = self._trend(since, now)
        ov = CatalogOverview(
            tables_count=tables, columns_count=columns, grade_distribution=grades,
            sensitive_count=sensitive, sensitive_ratio=ratio,
            quality_distribution=quality or {}, change_trend=trend,
            degraded_sources=degraded, computed_at=now,
            datasources_count=datasources,
        )
        return self._cache.put(ov)
