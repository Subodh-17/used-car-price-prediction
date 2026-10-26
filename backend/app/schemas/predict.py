"""Pydantic request / response schemas (numeric INR everywhere; formatting is a frontend concern)."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    make: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=80)
    variant: Optional[str] = Field(default=None, max_length=120)
    year: int = Field(ge=1980, le=2100)
    km_driven: float = Field(ge=0, le=1_000_000, allow_inf_nan=False)
    fuel: str = Field(min_length=1, max_length=20)
    transmission: str = Field(min_length=1, max_length=20)
    owner_count: Optional[int] = Field(default=None, ge=1, le=4)   # 4 = "4 or more"
    body_type: Optional[str] = Field(default=None, max_length=30)
    engine_cc: Optional[float] = Field(default=None, ge=300, le=9000, allow_inf_nan=False)
    max_power_bhp: Optional[float] = Field(default=None, ge=15, le=1500, allow_inf_nan=False)
    mileage: Optional[float] = Field(default=None, ge=2, le=60, allow_inf_nan=False)
    seats: Optional[int] = Field(default=None, ge=2, le=14)
    city: Optional[str] = Field(default=None, max_length=40)
    seller_type: Optional[str] = Field(default=None, max_length=30)


class Warning_(BaseModel):
    code: str
    message: str


class Interval(BaseModel):
    low_inr: int
    high_inr: int
    nominal_coverage: float
    empirical_test_coverage: float
    price_band: str
    method: str


class Effect(BaseModel):
    factor: str
    effect_inr: int


class Explanation(BaseModel):
    method: str
    effects: list[Effect]
    note: str


class ModelInfo(BaseModel):
    estimator: str
    data_version: str
    trained_utc: str
    valuation_year: int
    historical_reference_year: Optional[int] = None
    is_historical: bool = True
    valuation_reference_note: Optional[str] = None


class PredictResponse(BaseModel):
    estimated_price_inr: int
    interval: Optional[Interval] = None
    interval_note: Optional[str] = None
    warnings: list[Warning_]
    defaults_applied: list[dict[str, Any]]
    inputs_used: dict[str, Any]
    explanation: Optional[Explanation] = None
    model: ModelInfo
    disclaimer: str
    saved_to_history: bool = False


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    error: ErrorBody
