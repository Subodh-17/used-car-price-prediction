#!/usr/bin/env python
"""Independently re-evaluate the saved model on the held-out test split and compare with model_metrics.json."""
from __future__ import annotations

import json
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ucpp.features import to_model_frame  # noqa: E402
from ucpp.modeling import interval_band_index, regression_metrics  # noqa: E402


def main():
    df = pd.read_csv(ROOT / "data" / "processed" / "used_cars_clean.csv")
    split = pd.read_csv(ROOT / "reports" / "split_assignment.csv")
    test = df.merge(split[split.split == "test"][["row_id"]], on="row_id")
    model = joblib.load(ROOT / "models" / "used_car_price_model.joblib")      # trusted local artifact
    saved = json.loads((ROOT / "models" / "model_metrics.json").read_text(encoding="utf-8"))
    pred = model.predict(to_model_frame(test))
    y = test["price_inr"].values
    assert np.isfinite(pred).all() and (pred > 0).all(), "invalid predictions"
    m = regression_metrics(y, pred)
    qs = np.array([b["log_quantile"] for b in saved["interval"]["bands"]])[interval_band_index(pred)]
    cov = float((np.abs(np.log(y) - np.log(pred)) <= qs).mean())
    ok = abs(m["mae_inr"] - saved["test"]["mae_inr"]) < 1 and abs(cov - saved["interval"]["test_coverage"]) < 1e-6
    out = {"n_test": int(len(test)), "recomputed": m, "recomputed_interval_coverage": cov, "matches_saved_metrics": bool(ok)}
    (ROOT / "reports" / "evaluation_report.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
