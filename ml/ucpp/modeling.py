"""Pipeline construction, group-aware splitting, metrics and calibrated prediction intervals."""
from __future__ import annotations

import importlib.util
import math

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, OrdinalEncoder, StandardScaler

from .features import derive_vehicle_age
from .schema import CATEGORICAL_FEATURES, NUMERIC_FEATURES

PRICE_BANDS = [(0, 300_000, "< ₹3L"), (300_000, 600_000, "₹3–6L"), (600_000, 1_000_000, "₹6–10L"),
               (1_000_000, 2_000_000, "₹10–20L"), (2_000_000, 5_000_000, "₹20–50L"), (5_000_000, float("inf"), "≥ ₹50L")]


def log_target(estimator):
    """Log-price target with the exact inverse (expm1) applied on predict."""
    return TransformedTargetRegressor(regressor=estimator, func=np.log1p, inverse_func=np.expm1, check_inverse=False)


def _age_step():
    return ("age", FunctionTransformer(derive_vehicle_age, validate=False))


def _cat_cols(use_variant: bool):
    return [c for c in CATEGORICAL_FEATURES if use_variant or c != "variant"]


def tree_preprocessor(use_variant=True, impute_numeric=False):
    cats = _cat_cols(use_variant)
    cat = Pipeline([("impute", SimpleImputer(strategy="constant", fill_value="Unknown", keep_empty_features=True)),
                    ("encode", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=np.nan,
                                              min_frequency=3, max_categories=200))])
    num = (Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=True))]) if impute_numeric else "passthrough")
    return ColumnTransformer([("cat", cat, cats), ("num", num, NUMERIC_FEATURES)], remainder="drop", verbose_feature_names_out=False), len(cats)


def linear_preprocessor(use_variant=True):
    cats = _cat_cols(use_variant)
    cat = Pipeline([("impute", SimpleImputer(strategy="constant", fill_value="Unknown", keep_empty_features=True)),
                    ("onehot", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=15, sparse_output=False))])
    num = Pipeline([("impute", SimpleImputer(strategy="median", add_indicator=True)), ("scale", StandardScaler())])
    return ColumnTransformer([("cat", cat, cats), ("num", num, NUMERIC_FEATURES)], remainder="drop", verbose_feature_names_out=False)


def build_candidates(use_variant=True, seed=42) -> dict:
    """name -> (pipeline, param_grid or None). Grids are deliberately small."""
    cands = {}
    cands["median_baseline"] = (Pipeline([("reg", DummyRegressor(strategy="median"))]), None)
    cands["linear_regression"] = (Pipeline([_age_step(), ("prep", linear_preprocessor(use_variant)), ("reg", log_target(LinearRegression()))]), None)
    prep, _ = tree_preprocessor(use_variant, impute_numeric=True)
    cands["random_forest"] = (Pipeline([_age_step(), ("prep", prep), ("reg", log_target(RandomForestRegressor(n_estimators=150, n_jobs=-1, random_state=seed)))]),
                              {"reg__regressor__min_samples_leaf": [2], "reg__regressor__max_features": [0.5, 1.0]})
    prep, ncat = tree_preprocessor(use_variant)
    mask = [True] * ncat + [False] * len(NUMERIC_FEATURES)
    hgb = HistGradientBoostingRegressor(categorical_features=mask, max_iter=600, early_stopping=True, validation_fraction=0.1,
                                        n_iter_no_change=25, random_state=seed)
    cands["hist_gradient_boosting"] = (Pipeline([_age_step(), ("prep", prep), ("reg", log_target(hgb))]),
                                       {"reg__regressor__learning_rate": [0.05, 0.1], "reg__regressor__max_leaf_nodes": [20, 50],
                                        "reg__regressor__min_samples_leaf": [10, 30]})
    if importlib.util.find_spec("catboost") is not None:          # optional dependency
        try:
            from catboost import CatBoostRegressor
            cats = _cat_cols(use_variant)
            prep = ColumnTransformer([("cat", SimpleImputer(strategy="constant", fill_value="Unknown", keep_empty_features=True), cats), ("num", "passthrough", NUMERIC_FEATURES)],
                                     verbose_feature_names_out=False).set_output(transform="pandas")
            cb = CatBoostRegressor(iterations=800, learning_rate=0.06, depth=6, loss_function="RMSE", random_seed=seed, verbose=0, cat_features=cats)
            cands["catboost"] = (Pipeline([_age_step(), ("prep", prep), ("reg", log_target(cb))]), None)
        except Exception:  # pragma: no cover
            pass
    return cands


# ----------------------------------------------------------------------------- splitting
def group_folds(groups: np.ndarray, n_splits: int, seed: int):
    """Deterministic group k-fold: whole groups go to one fold (balanced greedily by size)."""
    rng = np.random.default_rng(seed)
    uniq, counts = np.unique(groups, return_counts=True)
    order = rng.permutation(len(uniq))
    uniq, counts = uniq[order], counts[order]
    idx = np.argsort(-counts, kind="stable")
    sizes = np.zeros(n_splits)
    fold_of = {}
    for i in idx:
        f = int(np.argmin(sizes)); fold_of[uniq[i]] = f; sizes[f] += counts[i]
    fold = np.array([fold_of[g] for g in groups])
    return [(np.where(fold != k)[0], np.where(fold == k)[0]) for k in range(n_splits)]


def group_holdout(groups: np.ndarray, test_fraction: float, seed: int):
    """One group-aware holdout: returns (dev_idx, test_idx) with no group in both."""
    rng = np.random.default_rng(seed)
    uniq, counts = np.unique(groups, return_counts=True)
    order = rng.permutation(len(uniq))
    target, acc, test_groups = test_fraction * len(groups), 0, set()
    for i in order:
        if acc >= target:
            break
        test_groups.add(uniq[i]); acc += counts[i]
    is_test = np.array([g in test_groups for g in groups])
    return np.where(~is_test)[0], np.where(is_test)[0]


# ----------------------------------------------------------------------------- metrics
def regression_metrics(y_true, y_pred) -> dict:
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    ape = np.abs(y_pred - y_true) / y_true
    return {"n": int(len(y_true)), "mae_inr": float(mean_absolute_error(y_true, y_pred)),
            "rmse_inr": float(math.sqrt(mean_squared_error(y_true, y_pred))), "r2": float(r2_score(y_true, y_pred)),
            "mape_pct": float(100 * ape.mean()), "median_ape_pct": float(100 * np.median(ape))}


def segment_metrics(df: pd.DataFrame, y_true, y_pred, by: str, min_n: int = 25, bins=None) -> list[dict]:
    d = pd.DataFrame({"seg": df[by].fillna("Unknown").astype(str).values if bins is None else bins, "y": np.asarray(y_true), "p": np.asarray(y_pred)})
    rows = []
    for seg, g in d.groupby("seg"):
        if len(g) >= min_n:
            m = regression_metrics(g["y"], g["p"]); m["segment"] = str(seg); rows.append(m)
    return sorted(rows, key=lambda r: -r["n"])


def price_band(prices) -> list[str]:
    out = []
    for p in prices:
        for lo, hi, name in PRICE_BANDS:
            if lo <= p < hi:
                out.append(name); break
    return out


# ----------------------------------------------------------------------------- intervals (split-conformal style, log scale)
def conformal_log_quantile(y_true, y_pred_oof, alpha: float) -> float:
    r = np.abs(np.log(np.asarray(y_true, float)) - np.log(np.asarray(y_pred_oof, float)))
    n = len(r)
    level = min(1.0, math.ceil((n + 1) * (1 - alpha)) / n)
    return float(np.quantile(r, level, method="higher"))


def interval_from_quantile(pred, q: float):
    pred = np.asarray(pred, float)
    return pred * math.exp(-q), pred * math.exp(q)


# ----------------------------------------------------------------------------- Mondrian (price-band) calibration
INTERVAL_BANDS = [(0, 300_000, "< ₹3L"), (300_000, 600_000, "₹3–6L"), (600_000, 1_000_000, "₹6–10L"),
                  (1_000_000, 2_000_000, "₹10–20L"), (2_000_000, float("inf"), "≥ ₹20L")]
_EDGES = [b[1] for b in INTERVAL_BANDS[:-1]]


def interval_band_index(prices) -> np.ndarray:
    """Band of each (predicted) price. A single flat relative width is badly calibrated across price levels, so the
    conformal quantile is computed separately inside each predicted-price band."""
    return np.searchsorted(_EDGES, np.asarray(prices, float), side="right")


def mondrian_log_quantiles(y_true, y_pred_oof, alpha: float, min_n: int = 100) -> list[dict]:
    y_true, y_pred_oof = np.asarray(y_true, float), np.asarray(y_pred_oof, float)
    overall = conformal_log_quantile(y_true, y_pred_oof, alpha)
    idx, out = interval_band_index(y_pred_oof), []
    for i, (lo, hi, name) in enumerate(INTERVAL_BANDS):
        m = idx == i
        q = conformal_log_quantile(y_true[m], y_pred_oof[m], alpha) if m.sum() >= min_n else overall
        out.append({"name": name, "lo_inr": lo, "hi_inr": None if hi == float("inf") else hi, "log_quantile": q, "n_calibration": int(m.sum()),
                    "fallback_to_overall": bool(m.sum() < min_n)})
    return out
