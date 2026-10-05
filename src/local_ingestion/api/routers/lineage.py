"""REST API for lineage (MOD-07).

Exposes upstream/downstream/impact (from the precomputed closure), ad-hoc SQL
parsing, manual edge annotation + external import, edge listing/deletion, and
closure rebuild. All reads are derived from collected edges; writes only touch
the platform catalog, never the business database.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Query

from local_ingestion.platform.lineage.parse import extract_column_edges, extract_table_edges
from local_ingestion.platform.lineage.repository import LineageRepository
from local_ingestion.platform.lineage.service import LineageService, get_default_lineage_service
from local_ingestion.platform.storage.session import session_scope

router = APIRouter(prefix="/api/v1/lineage", tags=["Lineage"])


def get_lineage_service() -> LineageService:
    return get_default_lineage_service()


def _repo() -> LineageRepository:
    return LineageRepository(session_scope)


@router.get("/tables/{fqn:path}/upstream")
def upstream(
    fqn: str,
    max_depth: int = Query(5, ge=1, le=20),
    svc: LineageService = Depends(get_lineage_service),
):
    return {"fqn": fqn, "nodes": [n.__dict__ for n in svc.upstream(fqn, max_depth)]}


@router.get("/tables/{fqn:path}/downstream")
def downstream(
    fqn: str,
    max_depth: int = Query(5, ge=1, le=20),
    svc: LineageService = Depends(get_lineage_service),
):
    return {"fqn": fqn, "nodes": [n.__dict__ for n in svc.downstream(fqn, max_depth)]}


@router.get("/tables/{fqn:path}/impact")
def impact(
    fqn: str,
    max_depth: int = Query(5, ge=1, le=20),
    svc: LineageService = Depends(get_lineage_service),
):
    return asdict(svc.impact_scope(fqn, "table", max_depth))


@router.post("/parse")
def parse_sql(payload: Dict[str, Any] = Body(...)):
    """Ad-hoc parse of a SQL/SELECT into table + column lineage (no persistence)."""
    sql = payload["sql"]
    ds_code = payload.get("ds_code", "ds")
    db = payload.get("db", "db")
    schema = payload.get("schema", "public")
    dialect = payload.get("dialect", "postgres")
    return {
        "table_edges": extract_table_edges(ds_code, db, schema, "_sub", sql, dialect),
        "column_edges": extract_column_edges(ds_code, db, schema, "_sub", sql, dialect),
    }


@router.get("/edges")
def list_edges(
    level: str = Query("table", pattern="^(table|column)$"),
    src_fqn: Optional[str] = Query(None),
    tgt_fqn: Optional[str] = Query(None),
):
    return _repo().list_edges(column=(level == "column"), src_fqn=src_fqn, tgt_fqn=tgt_fqn)


@router.post("/edges")
def add_edge(edge: Dict[str, Any] = Body(...)):
    """Manual lineage annotation (OpenMetadata parity)."""
    level = edge.get("level", "table")
    repo = _repo()
    if level == "column":
        repo.upsert_column_edge(
            edge["src_fqn"], edge["tgt_fqn"],
            edge_source=edge.get("edge_source", "manual"),
            confidence=float(edge.get("confidence", 1.0)),
        )
    else:
        repo.upsert_table_edge(
            edge["src_fqn"], edge["tgt_fqn"],
            edge_source=edge.get("edge_source", "manual"),
            confidence=float(edge.get("confidence", 1.0)),
        )
    repo.rebuild_closure()
    return {"ok": True}


@router.delete("/edges/{src_fqn:path}/{tgt_fqn:path}")
def delete_edge(src_fqn: str, tgt_fqn: str, column: bool = Query(False)):
    deleted = _repo().soft_delete_edge(src_fqn, tgt_fqn, column=column)
    if deleted:
        _repo().rebuild_closure()
    return {"ok": True, "deleted": deleted}


@router.post("/import")
def import_edges(payload: Dict[str, Any] = Body(...)):
    """Bulk import external lineage (ETL/BI systems, FR-16.5)."""
    edges: List[Dict[str, Any]] = payload.get("edges", [])
    repo = _repo()
    for e in edges:
        level = e.get("level", "table")
        if level == "column":
            repo.upsert_column_edge(e["src_fqn"], e["tgt_fqn"], edge_source="etl_system")
        else:
            repo.upsert_table_edge(e["src_fqn"], e["tgt_fqn"], edge_source="etl_system")
    repo.rebuild_closure()
    return {"ok": True, "imported": len(edges)}


@router.post("/closure/rebuild")
def rebuild_closure():
    _repo().rebuild_closure()
    return {"ok": True}
