"""Vehicle coverage registry built from the real training data (drives the selectors and coverage warnings)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .schema import BODY_TYPES, MIN_CITY_ROWS, MIN_MAKE_ROWS, MIN_MODEL_ROWS


def _mode(s: pd.Series):
    s = s.dropna()
    return None if s.empty else s.value_counts().index[0]


def _med(s: pd.Series):
    s = s.dropna()
    return None if s.empty else round(float(s.median()), 1)


def build_registry(df: pd.DataFrame) -> dict:
    makes = []
    models: dict[str, list] = {}
    for make, gm in df.groupby("make"):
        makes.append({"name": make, "count": int(len(gm)), "limited": bool(len(gm) < MIN_MAKE_ROWS)})
        entries = []
        for (mkey, mdisp), g in gm.groupby(["model", "model_display"]):
            variants = []
            for (vkey, vdisp), gv in g[g["variant"].notna()].groupby(["variant", "variant_display"]):
                v = {"key": vkey, "name": vdisp, "count": int(len(gv)), "fuel": _mode(gv["fuel"]), "transmission": _mode(gv["transmission"])}
                for col in ("engine_cc", "max_power_bhp", "mileage", "seats"):
                    v[col] = _med(gv[col])
                variants.append(v)
            variants.sort(key=lambda v: (-v["count"], v["name"]))
            entries.append({
                "key": mkey, "name": mdisp, "count": int(len(g)), "limited": bool(len(g) < MIN_MODEL_ROWS),
                "year_min": int(g["year"].min()), "year_max": int(g["year"].max()),
                "km_p99": float(g["km_driven"].quantile(0.99)),
                "fuels": [f for f in g["fuel"].value_counts().index], "transmissions": [t for t in g["transmission"].dropna().value_counts().index],
                "body_type": _mode(g["body_type"]), "variants": variants,
                "specs": {c: _med(g[c]) for c in ("engine_cc", "max_power_bhp", "mileage", "seats")},
            })
        entries.sort(key=lambda e: (-e["count"], e["name"]))
        models[make] = entries
    makes.sort(key=lambda m: (-m["count"], m["name"]))
    cities = df["city"].value_counts()
    return {
        "makes": makes, "models": models,
        "cities": [{"name": c, "count": int(n)} for c, n in cities.items() if n >= MIN_CITY_ROWS],
        "fuels": [f for f in df["fuel"].value_counts().index],
        "transmissions": [t for t in df["transmission"].dropna().value_counts().index],
        "body_types": [b for b in df["body_type"].dropna().value_counts().index] or list(BODY_TYPES),
        "seller_types": [b for b in df["seller_type"].dropna().value_counts().index],
        "ranges": {"year": [int(df["year"].min()), int(df["year"].max())], "km_driven_p99": float(df["km_driven"].quantile(0.99)),
                   "km_driven_max": float(df["km_driven"].max()), "price_inr_p95": float(df["price_inr"].quantile(0.95)),
                   "price_inr_p99": float(df["price_inr"].quantile(0.99)),
                   "engine_cc": [float(df["engine_cc"].min()), float(df["engine_cc"].max())],
                   "max_power_bhp": [float(df["max_power_bhp"].min()), float(df["max_power_bhp"].max())]},
    }
