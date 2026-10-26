"""1.2.14: LightGBM forecast explainer - read-only (GET only, no write, no training, no job)."""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..ml import forecast_explainer as fe

router = APIRouter(prefix="/api/forecast-explainer")


@router.get("")
def forecast_explainer(sku_id: str | None = None, fc_id: str | None = None, target_date: str | None = None):
    """How one value of the forecast in use was computed (default: a LightGBM series chosen automatically, the first
    forecast day from today). Always 200 with a `status` (OK / NO_FORECAST / NOT_FOUND / NOT_LIGHTGBM / MODEL_MISSING /
    DATA_UNAVAILABLE / UNSUPPORTED_STRATEGY / BAD_REQUEST) so the page can say why there is nothing to show."""
    return fe.explain(sku_id, fc_id, target_date)


@router.get("/trees")
def forecast_explainer_trees(offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=50),
                             sku_id: str | None = None, fc_id: str | None = None, target_date: str | None = None):
    """The path of one page of trees through the same explanation (computed once, cached per run / model / series)."""
    return fe.trees_page(offset, limit, sku_id, fc_id, target_date)
