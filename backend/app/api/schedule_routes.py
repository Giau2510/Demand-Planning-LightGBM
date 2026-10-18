"""1.1.8: data-flow schedules (D-1 closed days, D-0 today, daily training), each with its own switch."""
from __future__ import annotations

from fastapi import APIRouter

from ..jobs import flows

router = APIRouter(prefix="/api")


@router.get("/schedules")
def schedules():
    """Saved configuration, readiness, scheduler state, last / next runs of every flow (no job is run)."""
    return flows.overview()


@router.get("/schedules/{flow}")
def schedule(flow: str):
    return flows.flow_view(flow)


@router.get("/schedules/{flow}/preview")
def preview_schedule(flow: str):
    """1.2.6 dry run of a day-end flow (eod / close): what its next run would record today. Read-only, writes nothing."""
    return flows.preview(flow)


@router.put("/schedules/{flow}")
def save_schedule(flow: str, body: dict):
    """Save ONE flow (times and/or switch). Switching ON requires the flow to be ready (409 FLOW_NOT_READY)."""
    return flows.update_flow(flow, body)


@router.post("/schedules/{flow}/run")
def run_schedule_now(flow: str):
    """Run the flow's job once now (manual run, same locks); only when the flow is ready."""
    return flows.run_now(flow)
