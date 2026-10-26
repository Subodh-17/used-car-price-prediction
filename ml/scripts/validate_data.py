#!/usr/bin/env python
"""Validate the cleaned dataset (schema, units, ranges, duplicates, split leakage). Exit code 1 on any failure."""
from __future__ import annotations

import json
import sys
from pathlib import Path

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ucpp import schema as S  # noqa: E402

REQUIRED = ["row_id", "source", "group_id", "make", "model", "variant", "year", "snapshot_year", "km_driven", "fuel", "transmission",
            "seller_type", "owner_count", "city", "body_type", "engine_cc", "max_power_bhp", "mileage", "seats", "price_inr"]


def validate(csv: Path, report_json: Path, split_csv: Path | None = None) -> list[dict]:
    df = pd.read_csv(csv)
    checks: list[dict] = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "passed": bool(ok), "detail": str(detail)})

    miss = [c for c in REQUIRED if c not in df.columns]
    check("required columns present", not miss, miss)
    if miss:
        return checks
    check("row_id unique", df["row_id"].is_unique)
    price = pd.to_numeric(df["price_inr"], errors="coerce")
    check("price numeric & finite", price.notna().all() and np.isfinite(price).all())
    check(f"price >= ₹{S.MIN_PRICE_INR:,}", (price >= S.MIN_PRICE_INR).all(), f"min={price.min():,.0f}")
    check("price scale looks like rupees (median between ₹1L and ₹20L)", 100_000 <= price.median() <= 2_000_000, f"median={price.median():,.0f}")
    age = df["snapshot_year"] - df["year"]
    check("year within bounds and not after snapshot", ((df["year"] >= S.MIN_YEAR) & (age >= 0)).all())
    check("km_driven within bounds", df["km_driven"].between(0, S.MAX_KM).all())
    check("km per year plausible", ((age < 1) | (df["km_driven"] / age.clip(lower=1) <= S.MAX_KM_PER_YEAR)).all())
    check("fuel values valid", df["fuel"].isin(S.FUELS).all(), sorted(set(df["fuel"]) - set(S.FUELS)))
    check("transmission values valid", df["transmission"].dropna().isin(S.TRANSMISSIONS).all())
    check("body_type values valid", df["body_type"].dropna().isin(S.BODY_TYPES).all())
    check("seller_type values valid", df["seller_type"].dropna().isin(S.SELLER_TYPES).all())
    for col, (lo, hi) in S.BOUNDS.items():
        if col in df.columns and col not in {"year", "km_driven"}:
            check(f"{col} within bounds", df[col].dropna().between(lo, hi).all())
    check("no cross-source duplicate listings", not df.duplicated(["make", "model", "year", "km_driven", "fuel", "price_inr"]).any())
    check("make/model present", df[["make", "model"]].notna().all().all())
    rep_path = csv.parent / "cleaning_report.json"
    if rep_path.exists():
        rep = json.loads(rep_path.read_text())
        units = {k: v["verified_unit"] for k, v in rep["price_unit_verification"].items()}
        check("every source price unit verified", all(u in {"inr", "lakh"} for u in units.values()), units)
        check("no lakh-unit source used for training", "cardekho_small_lakhs" not in df["source"].unique())
    if split_csv and split_csv.exists():
        sp = pd.read_csv(split_csv).merge(df[["row_id", "group_id"]], on="row_id")
        leak = set(sp.loc[sp.split == "dev", "group_id"]) & set(sp.loc[sp.split == "test", "group_id"])
        check("no group shared between development and test sets", not leak, f"{len(leak)} shared groups")
    report_json.write_text(json.dumps({"rows": int(len(df)), "checks": checks}, indent=2))
    return checks


def main():
    csv = ROOT / "data" / "processed" / "used_cars_clean.csv"
    if not csv.exists():
        raise SystemExit(f"{csv} not found - run ml/scripts/ingest.py first")
    checks = validate(csv, ROOT / "reports" / "data_validation.json", ROOT / "reports" / "split_assignment.csv")
    for c in checks:
        print(("PASS " if c["passed"] else "FAIL ") + c["check"] + (f"  [{c['detail']}]" if c["detail"] and not c["passed"] else ""))
    failed = [c for c in checks if not c["passed"]]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
