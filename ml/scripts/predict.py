#!/usr/bin/env python
"""Reproducible command-line prediction using the exact same service as the API.

Example:
    python ml/scripts/predict.py --make "Maruti Suzuki" --model "Swift" --year 2016 --km 45000 --fuel Petrol --transmission Manual
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "backend"))
from app.services.model_service import ModelService, ServiceError  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    for name in ("make", "model", "fuel", "transmission"):
        ap.add_argument(f"--{name}", required=True)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--km", type=float, required=True, dest="km_driven")
    for name in ("variant", "city", "body_type", "seller_type"):
        ap.add_argument(f"--{name.replace('_', '-')}", dest=name)
    ap.add_argument("--owners", type=int, dest="owner_count")
    for name in ("engine_cc", "max_power_bhp", "mileage"):
        ap.add_argument(f"--{name.replace('_', '-')}", type=float, dest=name)
    ap.add_argument("--seats", type=int)
    args = vars(ap.parse_args())
    svc = ModelService(ROOT / "models", ROOT)
    try:
        print(json.dumps(svc.predict(args), indent=2, ensure_ascii=False))
    except ServiceError as e:
        print(json.dumps({"error": {"code": e.code, "message": e.message}}, indent=2)); sys.exit(2)


if __name__ == "__main__":
    main()
