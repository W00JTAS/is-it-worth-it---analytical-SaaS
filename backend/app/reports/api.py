from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query

from app.pricing.margin import CostConfig, MarginResult
from app.reports.aggregate import ReportSummary, build_summary
from app.reports.evaluate import ProductEvaluation
from app.reports.products import VALID_SORTS, VALID_STATUSES, ProductPage, list_product_rows
from app.scans.api import get_store
from app.scans.store import ScanStore

router = APIRouter()

REPORTABLE_STATUSES = ("done", "failed", "paused")


def _parse_decimal(name: str, value: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise HTTPException(
            status_code=400, detail=f"{name} must be a valid decimal, got {value!r}"
        )
    if not parsed.is_finite() or parsed < 0:
        raise HTTPException(
            status_code=400, detail=f"{name} must be a non-negative number, got {value!r}"
        )
    return parsed


def _cost_config_from_query(
    commission_pct: str, shipping_cost: str, vat_pct: str, returns_pct: str
) -> CostConfig:
    return CostConfig(
        commission_pct=_parse_decimal("commission_pct", commission_pct),
        shipping_cost=_parse_decimal("shipping_cost", shipping_cost),
        vat_pct=_parse_decimal("vat_pct", vat_pct),
        returns_pct=_parse_decimal("returns_pct", returns_pct),
    )


def _require_reportable_scan(store: ScanStore, scan_id: str):
    scan = store.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="scan not found")
    if scan.status.value not in REPORTABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"report is only available once a scan is done or failed, got {scan.status.value!r}",
        )
    return scan


def _margin_result_to_dict(result: MarginResult) -> dict:
    return {
        "scenario_pct": str(result.scenario_pct),
        "sale_price": str(result.sale_price),
        "net_revenue": str(result.net_revenue),
        "total_costs": str(result.total_costs),
        "margin": str(result.margin),
        "margin_pct": str(result.margin_pct),
    }


def _summary_to_dict(summary: ReportSummary) -> dict:
    return {
        "counts": {
            "total": summary.counts.total,
            "computable": summary.counts.computable,
            "not_checked": summary.counts.not_checked,
            "no_offer": summary.counts.no_offer,
            "currency_mismatch": summary.counts.currency_mismatch,
            "anomaly": summary.counts.anomaly,
        },
        "category_table": [
            {
                "category": row.category,
                "computable_count": row.computable_count,
                "excluded_count": row.excluded_count,
                "avg_margin_pct": str(row.avg_margin_pct) if row.avg_margin_pct is not None else None,
            }
            for row in summary.category_table
        ],
        "scenario_matrix": [
            {
                "scenario_pct": str(row.scenario_pct),
                "avg_margin_pct": str(row.avg_margin_pct) if row.avg_margin_pct is not None else None,
                "profitable_count": row.profitable_count,
            }
            for row in summary.scenario_matrix
        ],
    }


def _evaluation_to_dict(evaluation: ProductEvaluation) -> dict:
    record = evaluation.record
    offer = record.offer
    return {
        "id": record.id,
        "external_id": record.product.external_id,
        "name": record.product.name,
        "category": record.product.category,
        "ean": record.product.ean,
        "wholesale_price": str(record.product.wholesale_price),
        "currency": record.product.currency,
        "computable": evaluation.computable,
        "exclusion_reason": evaluation.exclusion_reason.value if evaluation.exclusion_reason else None,
        "anomaly_flag": evaluation.anomaly_flag.value if evaluation.anomaly_flag else None,
        "offer": (
            {
                "price": str(offer.price),
                "currency": offer.currency,
                "seller": offer.seller,
                "source_url": offer.source_url,
                "delivery_days": offer.delivery_days,
                "confidence": offer.confidence,
                "citations": list(offer.citations),
            }
            if offer is not None
            else None
        ),
        "margin_matrix": (
            [_margin_result_to_dict(r) for r in evaluation.margin_matrix]
            if evaluation.margin_matrix is not None
            else None
        ),
    }


def _product_page_to_dict(page: ProductPage) -> dict:
    return {
        "total": page.total,
        "page": page.page,
        "page_size": page.page_size,
        "rows": [_evaluation_to_dict(e) for e in page.rows],
    }


@router.get("/scans/{scan_id}/report/summary")
def get_report_summary(
    scan_id: str,
    commission_pct: str = Query(...),
    shipping_cost: str = Query(...),
    vat_pct: str = Query(...),
    returns_pct: str = Query(...),
    store: ScanStore = Depends(get_store),
):
    _require_reportable_scan(store, scan_id)
    cost_config = _cost_config_from_query(commission_pct, shipping_cost, vat_pct, returns_pct)
    records = store.list_all(scan_id)
    summary = build_summary(records, cost_config)
    return _summary_to_dict(summary)


@router.get("/scans/{scan_id}/report/products")
def get_report_products(
    scan_id: str,
    commission_pct: str = Query(...),
    shipping_cost: str = Query(...),
    vat_pct: str = Query(...),
    returns_pct: str = Query(...),
    category: str | None = Query(None),
    status: str | None = Query(None),
    sort: str = Query("category"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    store: ScanStore = Depends(get_store),
):
    _require_reportable_scan(store, scan_id)
    if sort not in VALID_SORTS:
        raise HTTPException(status_code=400, detail=f"sort must be one of {VALID_SORTS!r}, got {sort!r}")
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"status must be one of {VALID_STATUSES!r}, got {status!r}"
        )
    cost_config = _cost_config_from_query(commission_pct, shipping_cost, vat_pct, returns_pct)
    records = store.list_all(scan_id)
    result = list_product_rows(
        records, cost_config, category=category, status=status, sort=sort,
        page=page, page_size=page_size,
    )
    return _product_page_to_dict(result)
