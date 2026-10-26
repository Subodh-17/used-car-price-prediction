"""Framework-independent inference service: loads the trusted artifact once, validates coverage, predicts, explains.

Never returns a fabricated price: if the artifact is missing the service reports ``unavailable`` and every prediction
call raises ``ServiceError(503)``.
"""
from __future__ import annotations

import json
import logging
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger("ucp.model")

EXPLAIN_GROUPS = {
    "Make & model": ["make", "model"], "Variant": ["variant"], "Vehicle age": ["year", "snapshot_year"],
    "Kilometres driven": ["km_driven"], "Fuel type": ["fuel"], "Transmission": ["transmission"], "Ownership": ["owner_count"],
    "Engine, power & mileage": ["engine_cc", "max_power_bhp", "mileage", "seats"], "City": ["city"], "Body type": ["body_type"],
    "Seller type": ["seller_type"],
}
REQUIRED_FILES = ["used_car_price_model.joblib", "vehicle_registry.json", "model_metrics.json", "feature_schema.json", "training_metadata.json"]
DISCLAIMER = ("This is a statistical estimate based on historical listing data (not a live market feed). "
              "It is not a guaranteed sale price or a professional valuation.")


class ServiceError(Exception):
    def __init__(self, code: str, message: str, status: int = 422, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details or {}


def _norm(text) -> str:
    import re
    return re.sub(r"[\s\-]+", " ", str(text).strip().lower())


class ModelService:
    def __init__(self, models_dir: Path, ml_dir: Path):
        self.models_dir, self.ml_dir = Path(models_dir), Path(ml_dir)
        self.pipeline = None
        self.load_error: str | None = None
        self.registry = self.metrics = self.schema = self.meta = self.analytics = None
        self.background: pd.DataFrame | None = None
        self.load()

    # ------------------------------------------------------------------ loading
    @property
    def ready(self) -> bool:
        return self.pipeline is not None

    def load(self) -> None:
        missing = [f for f in REQUIRED_FILES if not (self.models_dir / f).is_file()]
        if missing:
            self.load_error = "Model artifacts not found. Run the training pipeline (see README)."
            log.error("model_artifacts_missing files=%s", missing)
            return
        try:
            if str(self.ml_dir) not in sys.path:
                sys.path.insert(0, str(self.ml_dir))           # makes `ucpp` importable for unpickling
            import joblib
            read = lambda n: json.loads((self.models_dir / n).read_text(encoding="utf-8"))  # noqa: E731
            self.registry, self.metrics, self.schema, self.meta = (read("vehicle_registry.json"), read("model_metrics.json"),
                                                                    read("feature_schema.json"), read("training_metadata.json"))
            if (self.models_dir / "analytics.json").is_file():
                self.analytics = read("analytics.json")
            if (self.models_dir / "explain_background.csv").is_file():
                self.background = pd.read_csv(self.models_dir / "explain_background.csv")
            # Trusted, locally trained artifact only: joblib/pickle executes code on load.
            self.pipeline = joblib.load(self.models_dir / "used_car_price_model.joblib")
            self._make_lookup = {_norm(m["name"]): m["name"] for m in self.registry["makes"]}
            self._model_lookup = {mk: {_norm(e["name"]): e for e in entries} for mk, entries in self.registry["models"].items()}
            self._model_lookup_key = {mk: {e["key"]: e for e in entries} for mk, entries in self.registry["models"].items()}
            self.valuation_year = int(self.schema["valuation_year"])
            self.load_error = None
            log.info("model_loaded estimator=%s data_version=%s", self.meta.get("selected_estimator"), self.meta.get("data_version"))
        except Exception:                                           # never leak paths / traces to clients
            log.exception("model_load_failed")
            self.pipeline, self.load_error = None, "Model artifacts could not be loaded."

    def require_ready(self) -> None:
        if not self.ready:
            raise ServiceError("model_unavailable", self.load_error or "Model unavailable.", 503)

    # ------------------------------------------------------------------ read-only views
    def health(self) -> dict:
        return {"status": "ok" if self.ready else "model_unavailable", "model_loaded": self.ready}

    def metadata(self) -> dict:
        self.require_ready()
        r, m = self.registry, self.metrics
        n_models = sum(len(v) for v in r["models"].values())
        interval = m["interval"]
        return {
            "model": {"estimator": self.meta["selected_estimator"], "trained_utc": self.meta["trained_utc"], "data_version": self.meta["data_version"],
                      "target": "listed selling price (INR)", "valuation_year": self.valuation_year, "libraries": self.meta["libraries"]},
            "coverage": {"rows": self.meta["rows"], "makes": len(r["makes"]), "models": n_models, "year_range": r["ranges"]["year"],
                         "fuels": r["fuels"], "transmissions": r["transmissions"], "body_types": r["body_types"], "cities": len(r["cities"])},
            "interval": {"available": bool(interval["validated"]), "nominal_coverage": interval["nominal_coverage"], "test_coverage": interval["test_coverage"]},
            "limits": {"max_year": self.valuation_year, "min_year": self.schema["bounds"]["year"][0], "bounds": self.schema["bounds"]},
            "disclaimer": DISCLAIMER,
        }

    def vehicle_options(self, make: str | None = None, model: str | None = None) -> dict:
        self.require_ready()
        r = self.registry
        if make is None:
            return {"makes": r["makes"], "fuels": r["fuels"], "transmissions": r["transmissions"], "body_types": r["body_types"],
                    "seller_types": r["seller_types"], "cities": r["cities"], "bounds": self.schema["bounds"], "valuation_year": self.valuation_year,
                    "year_range": r["ranges"]["year"]}
        mk = self._resolve_make(make)
        if model is None:
            return {"make": mk, "models": [{k: e[k] for k in ("name", "count", "limited", "year_min", "year_max", "fuels", "transmissions", "body_type")}
                                           for e in r["models"][mk]]}
        entry = self._resolve_model(mk, model)
        return {"make": mk, "model": entry}

    def metrics_view(self) -> dict:
        self.require_ready()
        return self.metrics

    def analytics_view(self) -> dict:
        self.require_ready()
        if self.analytics is None:
            raise ServiceError("analytics_unavailable", "Analytics data has not been generated.", 503)
        return self.analytics

    # ------------------------------------------------------------------ helpers
    def _resolve_make(self, make: str) -> str:
        mk = self._make_lookup.get(_norm(make))
        if mk is None:
            raise ServiceError("unsupported_vehicle", f"The manufacturer '{make}' is not in the training data, so no estimate can be given.", 422,
                               {"field": "make"})
        return mk

    def _resolve_model(self, make: str, model: str) -> dict:
        entry = self._model_lookup[make].get(_norm(model))
        if entry is None:
            raise ServiceError("unsupported_vehicle", f"The model '{model}' by {make} is not in the training data, so no estimate can be given. "
                               "It is never silently mapped to a different model.", 422, {"field": "model"})
        return entry

    # ------------------------------------------------------------------ prediction
    def predict(self, p: dict) -> dict:
        self.require_ready()
        warnings: list[dict] = []
        defaults: list[dict] = []
        add = lambda code, msg: warnings.append({"code": code, "message": msg})  # noqa: E731

        make = self._resolve_make(p["make"])
        entry = self._resolve_model(make, p["model"])
        year = int(p["year"])
        lo_y, hi_y = self.schema["bounds"]["year"][0], self.valuation_year
        if year > hi_y:
            raise ServiceError("year_out_of_coverage", f"Model year {year} is newer than the data used to train the model (up to {hi_y}). "
                               "No estimate is given for years outside the training coverage.", 422, {"field": "year", "max_year": hi_y})
        if year < lo_y:
            raise ServiceError("year_out_of_coverage", f"Model year {year} is below the supported minimum ({lo_y}).", 422, {"field": "year"})

        fuel = self._match_choice(p["fuel"], self.registry["fuels"], "fuel")
        transmission = self._match_choice(p["transmission"], self.registry["transmissions"], "transmission")
        body = p.get("body_type")
        if body:
            body = self._match_choice(body, self.registry["body_types"], "body_type")
        elif entry.get("body_type"):
            body = entry["body_type"]
            defaults.append({"field": "body_type", "value": body, "reason": "most common body type for this model in the training data"})
        seller = self._match_choice(p["seller_type"], self.registry["seller_types"], "seller_type") if p.get("seller_type") else None

        variant_key = None
        if p.get("variant"):
            vk = _norm(p["variant"])
            matched_v = next((v for v in entry["variants"] if v["key"] == vk), None)
            if matched_v:
                variant_key = vk
                if matched_v.get("count", 0) < 5:
                    add("limited_variant_data", f"Only {matched_v['count']} listings of the variant '{matched_v['name']}' were in the training data; the estimate relies more on the overall model.")
            else:
                variant_key = vk
                add("variant_unseen", f"The variant '{p['variant']}' was not seen for this model in the training data; the estimate relies on the other inputs.")
        city = None
        if p.get("city"):
            allowed = {_norm(c["name"]): c["name"] for c in self.registry["cities"]}
            city = allowed.get(_norm(p["city"]))
            if city is None:
                add("city_unsupported", f"City '{p['city']}' has too little training data and was not used.")

        # ---- coverage warnings (all derived from training data statistics)
        if self._make_count(make) < 30:
            add("limited_make_data", f"Only {self._make_count(make)} {make} listings were available for training; the estimate is less reliable.")
        if entry["limited"]:
            add("limited_model_data", f"Only {entry['count']} listings of this model were available for training; the estimate is less reliable.")
        if fuel not in entry["fuels"]:
            add("fuel_unseen_for_model", f"No {fuel} version of this model appears in the training data.")
        if entry["transmissions"] and transmission not in entry["transmissions"]:
            add("transmission_unseen_for_model", f"No {transmission} version of this model appears in the training data.")
        if not (entry["year_min"] <= year <= entry["year_max"]):
            add("year_outside_model_range", f"Training data for this model covers {entry['year_min']}–{entry['year_max']}; {year} is outside that range.")
        km = float(p["km_driven"])
        if km > max(entry["km_p99"] * 1.5, 1.0):
            add("km_above_typical", "Kilometres driven is far above what is typical for this model in the training data.")
        if (hi_y - year) >= 1 and km / max(hi_y - year, 1) > 60_000:
            add("km_per_year_high", "Very high yearly usage; estimates for extreme-usage vehicles are less reliable.")

        row = {"make": make, "model": entry["key"], "variant": variant_key, "fuel": fuel, "transmission": transmission, "seller_type": seller,
               "city": city, "body_type": body, "year": year, "snapshot_year": self.valuation_year, "km_driven": km,
               "owner_count": p.get("owner_count"), "engine_cc": p.get("engine_cc"), "max_power_bhp": p.get("max_power_bhp"),
               "mileage": p.get("mileage"), "seats": p.get("seats")}
        frame = self._frame(row)
        price = self._predict_value(frame)

        r = self.registry["ranges"]
        if price > r["price_inr_p99"]:
            add("extreme_price_band", "The estimate is above the 99th percentile of training prices; very few comparable vehicles were seen, so uncertainty is high.")
        elif price > r["price_inr_p95"]:
            add("high_price_band", "The estimate is in the top 5% of training prices; accuracy is lower for luxury and rare vehicles.")

        interval, interval_note = self._interval(price)
        explanation = self._explain(frame, price)
        return {
            "estimated_price_inr": round(price),
            "interval": interval,
            "interval_note": interval_note,
            "warnings": warnings, "defaults_applied": defaults,
            "inputs_used": {k: (None if (v is None or (isinstance(v, float) and math.isnan(v))) else v) for k, v in row.items() if k != "snapshot_year"},
            "explanation": explanation,
            "model": {"estimator": self.meta["selected_estimator"], "data_version": self.meta["data_version"], "trained_utc": self.meta["trained_utc"],
                      "valuation_year": self.valuation_year, "historical_reference_year": self.valuation_year, "is_historical": True,
                      "valuation_reference_note": f"Estimates reflect historical {self.valuation_year} listing price levels, not current-market prices."},
            "disclaimer": DISCLAIMER,
        }

    def _interval(self, price: float):
        """Calibrated range for the band the estimate falls in; only returned if that band validated on held-out data."""
        iv = self.metrics["interval"]
        none = "No empirically validated prediction range is available, so a single estimate is shown."
        if not iv.get("validated"):
            return None, none
        idx = int(np.searchsorted([b["hi_inr"] for b in iv["bands"][:-1]], price, side="right"))
        band = iv["bands"][idx]
        if not band["validated"]:
            return None, (f"A calibrated range is not available for estimates in the {band['name']} band "
                          f"(held-out coverage {band['test_coverage']:.0%} vs {iv['nominal_coverage']:.0%} target), so a single estimate is shown.")
        f = math.exp(band["log_quantile"])
        return ({"low_inr": round(price / f), "high_inr": round(price * f), "nominal_coverage": iv["nominal_coverage"],
                 "empirical_test_coverage": round(band["test_coverage"], 4), "price_band": band["name"],
                 "method": "Mondrian split-conformal on log-price, calibrated per predicted-price band"}, None)

    def _make_count(self, make: str) -> int:
        return next(m["count"] for m in self.registry["makes"] if m["name"] == make)

    def _match_choice(self, value: str, allowed: list[str], field: str) -> str:
        for a in allowed:
            if _norm(a) == _norm(value):
                return a
        raise ServiceError("unsupported_value", f"'{value}' is not a supported {field.replace('_', ' ')} (supported: {', '.join(allowed)}).", 422, {"field": field})

    def _frame(self, row: dict) -> pd.DataFrame:
        from ucpp.features import to_model_frame
        return to_model_frame(pd.DataFrame([row]))

    def _predict_value(self, frame: pd.DataFrame) -> float:
        try:
            out = np.asarray(self.pipeline.predict(frame), dtype=float)
        except Exception:
            log.exception("predict_failed")
            raise ServiceError("prediction_failed", "The model could not produce an estimate for these inputs.", 500) from None
        return self._validate_output(out)

    @staticmethod
    def _validate_output(out: np.ndarray) -> float:
        """Reject NaN / inf / negative / malformed outputs. Invalid predictions are never clamped or replaced."""
        if out.shape != (1,) or not np.isfinite(out).all() or float(out[0]) <= 0:
            log.error("invalid_model_output shape=%s", out.shape)
            raise ServiceError("invalid_prediction", "The model returned an invalid value, so no estimate is shown.", 500)
        return float(out[0])

    def _explain(self, frame: pd.DataFrame, base: float, n_bg: int = 60) -> dict | None:
        """One-factor-at-a-time substitution: effect = estimate - mean estimate when that factor is replaced by values of
        typical training listings. Effects interact and do not sum to the estimate. (Not SHAP.)"""
        if self.background is None or len(self.background) == 0:
            return None
        try:
            bg = self.background.head(n_bg).reset_index(drop=True)
            blocks, labels = [], []
            for label, cols in EXPLAIN_GROUPS.items():
                if all(pd.isna(frame.iloc[0][c]) for c in cols):
                    continue
                block = pd.concat([frame] * len(bg), ignore_index=True)
                for c in cols:
                    block[c] = bg[c].values
                blocks.append(block); labels.append(label)
            if not blocks:
                return None
            preds = np.asarray(self.pipeline.predict(pd.concat(blocks, ignore_index=True)), dtype=float)
            if not np.isfinite(preds).all():
                return None
            means = preds.reshape(len(blocks), len(bg)).mean(axis=1)
            effects = sorted(({"factor": l, "effect_inr": round(base - float(m))} for l, m in zip(labels, means)), key=lambda e: -abs(e["effect_inr"]))
            return {"method": "one-factor substitution against typical training listings", "effects": effects[:7],
                    "note": "Effect = how much higher (+) or lower (−) the estimate is than if that factor were typical. Effects interact and do not add up to the estimate."}
        except Exception:
            log.exception("explain_failed")
            return None
