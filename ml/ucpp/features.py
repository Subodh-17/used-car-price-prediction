"""Deterministic, target-free feature derivation shared by training and inference."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .schema import CATEGORICAL_FEATURES, PIPELINE_INPUT_COLUMNS


def derive_vehicle_age(X: pd.DataFrame) -> pd.DataFrame:
    """vehicle_age = snapshot_year - year (explicit valuation year, never the wall clock). Drops year/snapshot_year.
    Defined at module level so the fitted pipeline can be unpickled; used as the first pipeline step."""
    X = X.copy()
    X["vehicle_age"] = (X["snapshot_year"].astype(float) - X["year"].astype(float)).clip(lower=0)
    return X.drop(columns=["year", "snapshot_year"])


def to_model_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Select pipeline input columns in a fixed order; categoricals become plain objects with np.nan for missing."""
    out = pd.DataFrame(index=df.index)
    for col in PIPELINE_INPUT_COLUMNS:
        if col not in df.columns:
            out[col] = np.nan
        elif col in CATEGORICAL_FEATURES:
            s = df[col].astype(object)
            out[col] = s.where(s.notna(), np.nan)
        else:
            out[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    return out[PIPELINE_INPUT_COLUMNS]
