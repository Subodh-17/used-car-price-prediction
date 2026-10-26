from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.concurrency import run_in_threadpool

from ..schemas.predict import ErrorResponse, PredictRequest, PredictResponse
from ..services.model_service import ServiceError

log = logging.getLogger("ucp.api")
router = APIRouter(prefix="/api")
ERR = {422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}, 500: {"model": ErrorResponse}}


def _svc(request: Request):
    return request.app.state.service


@router.get("/health")
def health(request: Request, response: Response):
    res = _svc(request).health()
    if not res.get("model_loaded"):
        response.status_code = 503
    return res


@router.get("/metadata", responses=ERR)
def metadata(request: Request):
    return _svc(request).metadata()


@router.get("/vehicle-options", responses=ERR)
def vehicle_options(request: Request, make: str | None = Query(default=None, max_length=60), model: str | None = Query(default=None, max_length=80)):
    if model and not make:
        raise ServiceError("validation_error", "'model' requires 'make'.", 422)
    return _svc(request).vehicle_options(make, model)


@router.get("/model-metrics", responses=ERR)
def model_metrics(request: Request):
    return _svc(request).metrics_view()


@router.get("/analytics", responses=ERR)
def analytics(request: Request):
    return _svc(request).analytics_view()


@router.post("/predict", response_model=PredictResponse, responses=ERR)
async def predict(body: PredictRequest, request: Request, x_client_id: str | None = Header(default=None)):
    svc, store, settings = _svc(request), request.app.state.history, request.app.state.settings
    try:
        result = await asyncio.wait_for(run_in_threadpool(svc.predict, body.model_dump()), timeout=settings.predict_timeout_s)
    except asyncio.TimeoutError:
        raise ServiceError("timeout", "The estimate took too long. Please try again.", 504) from None
    saved = False
    if x_client_id and store.valid_client_id(x_client_id):
        try:
            iv = result["interval"]
            store.add(x_client_id, f"{result['model']['estimator']}@{result['model']['data_version']}", result["inputs_used"],
                      result["estimated_price_inr"], iv["low_inr"] if iv else None, iv["high_inr"] if iv else None)
            saved = True
        except Exception:
            log.exception("history_write_failed")
    result["saved_to_history"] = saved
    return result


@router.get("/history")
def history(request: Request, x_client_id: str | None = Header(default=None)):
    store = request.app.state.history
    if not store.valid_client_id(x_client_id):
        raise ServiceError("missing_client_id", "A valid X-Client-Id header is required.", 400)
    return {"items": store.list(x_client_id)}


@router.delete("/history")
def clear_history(request: Request, x_client_id: str | None = Header(default=None)):
    store = request.app.state.history
    if not store.valid_client_id(x_client_id):
        raise ServiceError("missing_client_id", "A valid X-Client-Id header is required.", 400)
    return {"deleted": store.clear(x_client_id)}
