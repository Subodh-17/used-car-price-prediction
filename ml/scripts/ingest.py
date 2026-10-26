#!/usr/bin/env python
"""Ingest raw dataset archives into one cleaned, canonical INR dataset.

Usage:
    python ml/scripts/ingest.py --raw-dir ml/data/raw [--exclude-source third_listings]

Accepts .zip archives or loose .csv files in --raw-dir; sources are recognised by the CSV file names inside
(no downloads are attempted). Writes to ml/data/processed/:
    used_cars_clean.csv, rejected_records.csv, cleaning_report.json
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
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
from ucpp import cleaning as C  # noqa: E402
from ucpp import schema as S  # noqa: E402

KNOWN_FILES = {
    "Car details v3.csv": "cardekho_v3",
    "CAR DETAILS FROM CAR DEKHO.csv": "cardekho_old",
    "car details v4.csv": "cardekho_v4",
    "car data.csv": "cardekho_small_lakhs",
    "UsedCars_Combined.csv": "city_listings",
    "Used_Car_Price_Prediction.csv": "third_listings",
}
# Files that exist inside the archives but are deliberately NOT used.
IGNORED_FILES = {
    "Dataset.csv": "engineered copy of the city listings containing target-derived columns (inv_car_price, std_invprice, best_buy*) -> target leakage",
    "UsedCars_Banglore.csv": "per-city subset already contained in UsedCars_Combined.csv", "UsedCars_Chennai.csv": "subset of UsedCars_Combined.csv",
    "UsedCars_Delhi.csv": "subset of UsedCars_Combined.csv", "UsedCars_Hyderabad.csv": "subset of UsedCars_Combined.csv",
    "UsedCars_Kolkata.csv": "subset of UsedCars_Combined.csv", "UsedCars_Mumbai.csv": "subset of UsedCars_Combined.csv",
    "UsedCars_Pune.csv": "subset of UsedCars_Combined.csv",
}


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def collect_sources(raw_dir: Path, work_dir: Path):
    """Return {source_name: csv_path}, file inventory (with sha256) and the list of ignored files."""
    found, inventory, ignored = {}, [], []
    work_dir.mkdir(parents=True, exist_ok=True)

    def register(name: str, data: bytes, origin: str):
        digest = sha256_bytes(data)
        if name in KNOWN_FILES:
            target = work_dir / name
            target.write_bytes(data)
            found[KNOWN_FILES[name]] = target
            inventory.append({"file": name, "origin": origin, "sha256": digest, "bytes": len(data), "used_as": KNOWN_FILES[name]})
        elif name in IGNORED_FILES:
            ignored.append({"file": name, "origin": origin, "reason": IGNORED_FILES[name]})
        elif name.lower().endswith(".csv"):
            ignored.append({"file": name, "origin": origin, "reason": "unrecognised file name"})

    for p in sorted(raw_dir.iterdir()):
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                for info in z.infolist():
                    register(Path(info.filename).name, z.read(info), p.name)
        elif p.suffix.lower() == ".csv":
            register(p.name, p.read_bytes(), "loose")
    return found, inventory, ignored


def verify_price_units(found: dict, v3_median: float) -> dict:
    """Verify (not assume) each source's price unit by comparing medians against the CarDekho v3 INR column,
    whose values (e.g. 450000 for a 2014 Swift Dzire diesel) are plainly rupees."""
    out = {}
    refs = {"cardekho_v3": ("selling_price", "name"), "cardekho_old": ("selling_price", "name"), "cardekho_v4": ("Price", None),
            "city_listings": ("price", None), "third_listings": ("sale_price", None), "cardekho_small_lakhs": ("Selling_Price", None)}
    for src, (col, _) in refs.items():
        if src not in found:
            continue
        med = float(pd.read_csv(found[src])[col].median())
        ratio = med / v3_median
        unit = "lakh" if 0.2e-5 < ratio < 5e-5 else "inr" if 0.1 < ratio < 10 else "UNVERIFIED"
        out[src] = {"column": col, "median": med, "ratio_to_cardekho_v3_median_inr": round(ratio, 8), "verified_unit": unit}
        if unit == "UNVERIFIED":
            raise SystemExit(f"Cannot verify the price unit of {src} (median ratio {ratio}); refusing to continue.")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", default=str(ROOT / "data" / "raw"))
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "processed"))
    ap.add_argument("--exclude-source", action="append", default=[], help="source name(s) to leave out, e.g. third_listings")
    args = ap.parse_args()
    raw_dir, out_dir = Path(args.raw_dir), Path(args.out_dir)
    if not raw_dir.is_dir() or not any(raw_dir.iterdir()):
        raise SystemExit(f"No raw data in {raw_dir}. See README ('Dataset download instructions').")
    out_dir.mkdir(parents=True, exist_ok=True)
    found, inventory, ignored = collect_sources(raw_dir, out_dir / "_extracted")
    if not found:
        raise SystemExit("No recognised dataset files found.")
    if "cardekho_v3" not in found:
        raise SystemExit("cardekho_v3 ('Car details v3.csv') is required as the INR reference for unit verification.")
    used_inventory = [i for i in inventory if i["used_as"] not in args.exclude_source]
    excluded_inventory = [i for i in inventory if i["used_as"] in args.exclude_source]
    report: dict = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "inventory": inventory,
                    "used_inventory": used_inventory, "excluded_inventory": excluded_inventory,
                    "excluded_sources": args.exclude_source, "ignored_files": ignored}
    # data_version is computed from USED sources only so it changes when the approved source list changes
    report["data_version"] = sha256_bytes("".join(sorted(i["sha256"] for i in used_inventory)).encode())[:16]

    v3_med = float(pd.read_csv(found["cardekho_v3"])["selling_price"].median())
    report["price_unit_verification"] = verify_price_units(found, v3_med)
    if "cardekho_small_lakhs" in found:
        small = C.load_cardekho_small_lakhs(found["cardekho_small_lakhs"])
        report["small_dataset_note"] = {
            "file": "car data.csv", "rows": int(len(small)), "unit": "lakh (verified)",
            "example": {"raw_lakh": 5.5, "inr": 550000.0},
            "used_for_training": False,
            "reason": "no separate make column, tiny, includes Present_Price (target-adjacent) and overlaps v3 in ways that cannot be reliably de-duplicated",
        }

    # ---- build canonical frame
    third = pd.read_csv(found["third_listings"]) if ("third_listings" in found and "third_listings" not in args.exclude_source) else pd.DataFrame(columns=["make", "model"])
    resolver = C.FamilyResolver(C.build_families(third))
    frames = []
    loaders = {
        "cardekho_v3": lambda p: C.load_cardekho_v3(p, resolver, "cardekho_v3"),
        "cardekho_old": lambda p: C.load_cardekho_v3(p, resolver, "cardekho_old"),
        "cardekho_v4": lambda p: C.load_cardekho_v4(p, resolver),
        "city_listings": lambda p: C.load_city_listings(p, resolver),
        "third_listings": C.load_third,
    }
    for name, loader in loaders.items():
        if name in found and name not in args.exclude_source:
            frames.append(loader(found[name]))
    df = pd.concat(frames, ignore_index=True)
    # Snapshot year (the year the listing prices refer to). Only third_listings carries listing dates (ad_created_on);
    # other sources have none, so we ASSUME snapshot year = newest model year present in that source. Documented limitation.
    snap = df.groupby("source")["year"].max()
    assumed = {}
    for src, grp in df.groupby("source"):
        if src == "third_listings":
            continue
        assumed[src] = int(snap[src])
        df.loc[grp.index, "snapshot_year"] = snap[src]
    report["snapshot_year_assumption"] = {
        "rule": "listing dates exist only in third_listings (ad_created_on year). For all other sources snapshot year is ASSUMED = newest model year in that source.",
        "assumed": assumed,
        "third_listings_ad_date_range": [str(pd.to_datetime(third["ad_created_on"], errors="coerce").min()),
                                         str(pd.to_datetime(third["ad_created_on"], errors="coerce").max())] if ("ad_created_on" in third and len(third)) else None,
    }
    df["snapshot_year"] = df["snapshot_year"].fillna(df.groupby("source")["year"].transform("max"))
    df["row_id"] = df["source"] + ":" + df["source_row"].astype(int).astype(str)
    report["rows_loaded_by_source"] = df["source"].value_counts().to_dict()

    # ---- keys + display casing
    for col in ("model_display", "variant_display"):
        df[col] = df[col].fillna("").astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    df["model"] = df["model_display"].map(C.norm_key)
    df["variant"] = df["variant_display"].map(C.norm_key).replace({"": np.nan, "nan": np.nan})
    proper = df["source"] != "third_listings"

    def display_map(col_key, col_disp, by):
        m = {}
        for keys, g in df.groupby(by):
            if not isinstance(keys, tuple):
                keys = (keys,)
            m[keys] = C.pick_display(g[col_disp].astype(str), proper.loc[g.index])
        return m
    mm = display_map("model", "model_display", ["make", "model"])
    df["model_display"] = [mm[(a, b)] for a, b in zip(df["make"], df["model"])]
    vv = df[df["variant"].notna()]
    vmap = {}
    for keys, g in vv.groupby(["make", "model", "variant"]):
        vmap[keys] = C.pick_display(g["variant_display"].astype(str), proper.loc[g.index])
    df["variant_display"] = [vmap.get((a, b, c)) if isinstance(c, str) else None for a, b, c in zip(df["make"], df["model"], df["variant"])]

    # ---- body type registry (fill only where a (make, model) has a clear dominant stated body type)
    df["body_type"] = df["body_type"].astype(object)
    df["body_type_inferred"] = False
    stated = df[df["body_type"].notna()]
    reg = {}
    if len(stated):
        for (mk, md), g in stated.groupby(["make", "model"]):
            top = g["body_type"].value_counts()
            if len(g) >= 5 and top.iloc[0] / len(g) >= 0.9:
                reg[(mk, md)] = top.index[0]
        miss = df["body_type"].isna()
        fill = pd.Series([reg.get((a, b)) for a, b in zip(df["make"], df["model"])], index=df.index, dtype=object)
        to_fill = miss & fill.notna()
        df.loc[to_fill, "body_type_inferred"] = True
        df.loc[to_fill, "body_type"] = fill[to_fill]
    report["body_type_registry"] = {"models_with_registry_body_type": len(reg), "rows_filled": int(df["body_type_inferred"].sum()),
                                    "rule": ">=5 rows with a stated body type and >=90% agreement for that (make, model)"}

    # ---- cleaning rules (first matching reason wins)
    reasons = pd.Series("", index=df.index)

    def reject(mask, reason):
        nonlocal reasons
        m = mask & (reasons == "")
        reasons[m] = reason

    age = df["snapshot_year"] - df["year"]
    reject(df[["make", "model", "year", "km_driven", "fuel", "price_inr"]].isna().any(axis=1) | (df["model"] == ""), "missing_required_field")
    reject(df["price_inr"] < S.MIN_PRICE_INR, f"implausible_price_below_{S.MIN_PRICE_INR}")
    reject((df["year"] < S.MIN_YEAR) | (age < 0), "invalid_year")
    reject((df["km_driven"] < 0) | (df["km_driven"] > S.MAX_KM), "impossible_km_driven")
    reject((age >= 1) & (df["km_driven"] / age.clip(lower=1) > S.MAX_KM_PER_YEAR), "implausible_km_per_year")
    reject((age >= 5) & (df["km_driven"] < 100), "implausible_odometer_for_age")
    # owner count 'Test Drive Car'/'UnRegistered Car' were mapped to NaN -> kept (owner unknown) not rejected.
    rejected = [df[reasons != ""].assign(reject_reason=reasons[reasons != ""])]
    df = df[reasons == ""].copy()

    # ---- duplicates
    feat_cols = ["variant", "transmission", "seller_type", "owner_count", "city", "body_type", "engine_cc", "max_power_bhp", "mileage", "seats"]
    df["_richness"] = df[feat_cols].notna().sum(axis=1)
    within = df.duplicated(subset=["source", "make", "model", "variant", "year", "km_driven", "fuel", "transmission", "owner_count", "seller_type", "city", "price_inr"], keep="first")
    rejected.append(df[within].assign(reject_reason="duplicate_within_source"))
    df = df[~within]
    df = df.sort_values(["_richness"], ascending=False, kind="stable")
    cross_key = ["make", "model", "year", "km_driven", "fuel", "price_inr"]
    cross = df.duplicated(subset=cross_key, keep="first")
    rejected.append(df[cross].assign(reject_reason="duplicate_across_sources"))
    df = df[~cross].sort_index().drop(columns="_richness")
    rej = pd.concat(rejected, ignore_index=True)[["row_id", "source", "make", "model_display", "year", "km_driven", "price_inr", "reject_reason"]]

    # ---- group key for leakage-safe splitting (near-duplicate listings share a group)
    df["group_id"] = (df["make"] + "|" + df["model"] + "|" + df["year"].astype(int).astype(str) + "|" + df["fuel"] + "|"
                      + (df["km_driven"] / 1000).round().astype(int).astype(str))

    # ---- outlier REVIEW (nothing removed)
    lp = np.log(df["price_inr"])
    grp = lp.groupby([df["make"], df["model"]])
    q1, q3, n = grp.transform(lambda s: s.quantile(.25)), grp.transform(lambda s: s.quantile(.75)), grp.transform("size")
    flag = (n >= 10) & ((lp > q3 + 3 * (q3 - q1)) | (lp < q1 - 3 * (q3 - q1)))
    top = df[flag].nlargest(15, "price_inr")[["row_id", "make", "model_display", "year", "km_driven", "price_inr"]]
    report["outlier_review"] = {
        "method": "log-price IQR*3 within (make, model) groups with n>=10; INFORMATIONAL ONLY - no row removed because high prices are legitimate luxury vehicles",
        "flagged_rows": int(flag.sum()), "examples": top.to_dict("records"),
        "price_quantiles_inr": {str(q): float(df["price_inr"].quantile(q)) for q in (0.01, 0.25, 0.5, 0.75, 0.99)},
    }
    report["rejected_by_reason"] = rej["reject_reason"].value_counts().to_dict()
    report["rejected_by_source"] = rej.groupby(["source", "reject_reason"]).size().rename("n").reset_index().to_dict("records")
    report["rows_clean"] = int(len(df))
    report["rows_clean_by_source"] = df["source"].value_counts().to_dict()
    report["missing_share_clean"] = {c: round(float(df[c].isna().mean()), 4) for c in
                                     ["variant", "transmission", "seller_type", "owner_count", "city", "body_type", "engine_cc", "max_power_bhp", "mileage", "seats"]}
    report["clean_ranges"] = {"year": [int(df.year.min()), int(df.year.max())], "snapshot_year_max": int(df.snapshot_year.max()),
                              "km_driven_max": float(df.km_driven.max()), "price_inr": [float(df.price_inr.min()), float(df.price_inr.max())]}
    report["target"] = ("price_inr = listed selling price in rupees as given by the sources (asking/listing prices, "
                        "not confirmed transaction prices). All verified INR; no scaling applied to any training source.")
    report["leakage_exclusions"] = {
        "third_listings": ["broker_quote", "original_price", "emi_starts_from", "booking_down_pymnt", "car_rating", "times_viewed", "assured_buy", "is_hot", "fitness_certificate", "warranty_avail", "car_availability", "source"],
        "city_listings_Dataset.csv": ["inv_car_price", "inv_car_dist", "std_invprice", "best_buy1", "best_buy2"],
        "car data.csv": ["Present_Price"],
    }
    out_cols = ["row_id", "source", "group_id"] + [c for c in df.columns if c not in {"row_id", "source", "group_id", "source_row"}]
    out_cols = list(dict.fromkeys(out_cols))
    df[out_cols].to_csv(out_dir / "used_cars_clean.csv", index=False)
    rej.to_csv(out_dir / "rejected_records.csv", index=False)
    (out_dir / "cleaning_report.json").write_text(json.dumps(report, indent=2, default=str))
    import shutil
    shutil.rmtree(out_dir / "_extracted", ignore_errors=True)
    # Invalidate stale split / evaluation artifacts from any prior training run so that train.py produces fresh ones
    reports_dir = ROOT / "reports"
    for stale in ("split_assignment.csv", "test_predictions.csv", "data_validation.json", "evaluation_report.json"):
        (reports_dir / stale).unlink(missing_ok=True)
    print(json.dumps({k: report[k] for k in ("data_version", "excluded_sources", "rows_loaded_by_source", "rejected_by_reason", "rows_clean", "rows_clean_by_source", "price_unit_verification")}, indent=2, default=str))


if __name__ == "__main__":
    main()
