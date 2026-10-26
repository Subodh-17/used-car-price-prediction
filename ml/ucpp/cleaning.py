"""Source loaders and canonicalisation: every source is mapped onto one canonical schema.

Canonical columns: source, source_row, make, model, variant, model_display, variant_display,
year, snapshot_year, km_driven, fuel, transmission, seller_type, owner_count, city, body_type,
engine_cc, max_power_bhp, mileage, seats, price_inr.

``model`` / ``variant`` hold lower-cased matching keys; the ``*_display`` columns keep a readable
casing for the UI. Nothing here reads or uses the target to build features.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from .units import parse_engine_cc, parse_mileage, parse_power_bhp, to_inr

CANON_COLUMNS = [
    "source", "source_row", "make", "model", "variant", "model_display", "variant_display", "year",
    "snapshot_year", "km_driven", "fuel", "transmission", "seller_type", "owner_count", "city",
    "body_type", "engine_cc", "max_power_bhp", "mileage", "seats", "price_inr",
]

# --------------------------------------------------------------------------- makes
_MAKE_ALIASES = {
    "maruti": "Maruti Suzuki", "marutisuzuki": "Maruti Suzuki", "mercedesbenz": "Mercedes-Benz",
    "mercedes": "Mercedes-Benz", "land": "Land Rover", "landrover": "Land Rover", "mini": "Mini",
    "ssangyong": "SsangYong", "mahindrarenault": "Mahindra Renault", "ashok": "Ashok Leyland",
    "rollsroyce": "Rolls-Royce", "mg": "MG", "bmw": "BMW", "force": "Force", "volkswagen": "Volkswagen",
}


def canon_make(raw: str) -> str:
    key = re.sub(r"[^a-z]", "", str(raw).lower())
    if key in _MAKE_ALIASES:
        return _MAKE_ALIASES[key]
    return " ".join(w.capitalize() for w in str(raw).strip().split())


_CITY_ALIASES = {
    "bangalore": "Bengaluru", "bengaluru": "Bengaluru", "new delhi": "Delhi", "delhi": "Delhi",
    "gurgaon": "Gurgaon", "gurugram": "Gurgaon", "navi mumbai": "Navi Mumbai", "bombay": "Mumbai",
}


def canon_city(raw) -> str | None:
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return None
    s = re.sub(r"\s+", " ", str(raw).strip().lower())
    if not s:
        return None
    return _CITY_ALIASES.get(s, " ".join(w.capitalize() for w in s.split()))


def canon_fuel(raw) -> str | None:
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return None
    s = str(raw).strip().lower()
    if s in {"petrol", "gasoline"}:
        return "Petrol"
    if s == "diesel":
        return "Diesel"
    if s in {"electric", "ev"}:
        return "Electric"
    if s == "hybrid":
        return "Hybrid"
    if "cng" in s:                       # 'petrol + cng', 'petrol & cng', 'cng + cng', 'cng + 1'
        return "CNG"
    if "lpg" in s:
        return "LPG"
    return "Other"                        # e.g. 'petrol + 1' (ambiguous bi-fuel notation)


def canon_transmission(raw) -> str | None:
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return None
    s = str(raw).strip().lower()
    return {"manual": "Manual", "automatic": "Automatic"}.get(s)


_TRANS_TOKENS = {"mt": "Manual", "manual": "Manual", "at": "Automatic", "amt": "Automatic", "cvt": "Automatic",
                 "dct": "Automatic", "dsg": "Automatic", "automatic": "Automatic", "tiptronic": "Automatic",
                 "tip": "Automatic"}


def transmission_from_text(text: str) -> str | None:
    """Only explicit tokens count (MT, AT, AMT, CVT, DCT ...). Otherwise unknown (None)."""
    found = {_TRANS_TOKENS[t] for t in re.findall(r"[a-z]+", str(text).lower()) if t in _TRANS_TOKENS}
    return found.pop() if len(found) == 1 else None


_BODY_MAP = {"hatchback": "Hatchback", "sedan": "Sedan", "suv": "SUV", "luxury suv": "SUV", "luxury sedan": "Sedan",
             "crossover": "Crossover", "muv": "MUV/MPV", "mpv": "MUV/MPV", "minivan": "MUV/MPV", "coupe": "Coupe",
             "convertible": "Convertible", "wagon": "Wagon", "van": "Van", "pickup": "Pickup"}


def canon_body(raw) -> str | None:
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return None
    return _BODY_MAP.get(str(raw).strip().lower(), "Other")


def canon_seller(raw) -> str | None:
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return None
    s = str(raw).strip().lower()
    return {"individual": "Individual", "dealer": "Dealer", "trustmark dealer": "Trustmark Dealer",
            "corporate": "Corporate", "commercial registration": "Commercial Registration"}.get(s)


def owner_from_text(raw) -> float | None:
    """First/Second/Third/Fourth&Above -> 1..4. 'Test Drive Car' / 'UnRegistered Car' -> None (not an ownership count)."""
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return None
    s = str(raw).strip().lower()
    for key, val in (("first", 1), ("second", 2), ("third", 3), ("fourth", 4), ("4 or more", 4)):
        if s.startswith(key):
            return float(val)
    return None


# --------------------------------------------------------------------------- model / variant split
# Multi-word model families that cannot be recovered by "first token" alone.
_SEED_FAMILIES = [
    "swift dzire", "wagon r", "alto k10", "alto 800", "grand i10", "santro xing", "grand vitara", "s-cross",
    "land cruiser", "range rover sport", "range rover evoque", "range rover velar", "range rover", "grand cherokee",
    "pajero sport", "elite i20", "eon", "xuv500", "e-class", "c-class", "s-class", "a-class", "b-class", "gl-class",
    "m-class", "cooper countryman", "x-trail", "city zx", "accent viva", "creta", "new santro", "grand i10 nios",
]
_YEARS = re.compile(r"\[?\(?\b(?:19|20)\d{2}\s*-\s*(?:19|20)?\d{2}\b\)?\]?")
_TRAILING_DISPLACEMENT = re.compile(r"\s+\d\.\d$")


def clean_text(s: str) -> str:
    s = _YEARS.sub(" ", str(s))
    s = re.sub(r"[\[\]()]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


class FamilyResolver:
    """Splits 'Swift Dzire VDI' into ('swift dzire', 'VDI') using families observed in clean sources."""

    def __init__(self, families_by_make: dict[str, set[str]]):
        self.families = families_by_make

    def split(self, make: str, rest: str) -> tuple[str, str]:
        tokens = clean_text(rest).split()
        if not tokens:
            return "", ""
        known = self.families.get(make, set()) | self.families.get("*", set())
        for n in (3, 2, 1):
            if len(tokens) >= n and " ".join(tokens[:n]).lower() in known:
                return " ".join(tokens[:n]), " ".join(tokens[n:])
        if len(tokens) >= 2 and tokens[1].lower() in {"series", "class"}:
            return " ".join(tokens[:2]), " ".join(tokens[2:])
        return tokens[0], " ".join(tokens[1:])


def build_families(third: pd.DataFrame) -> dict[str, set[str]]:
    fams: dict[str, set[str]] = defaultdict(set)
    fams["*"].update(_SEED_FAMILIES)
    for make_raw, model_raw in zip(third["make"], third["model"]):
        fam = _TRAILING_DISPLACEMENT.sub("", str(model_raw).strip().lower())
        fams[canon_make(make_raw)].add(fam)
    return fams


def strip_make_prefix(name: str, make: str, raw_make: str | None = None) -> str:
    name = str(name).strip()
    candidates = {make.lower(), (raw_make or "").lower(), make.split()[0].lower()}
    for cand in sorted((c for c in candidates if c), key=len, reverse=True):
        if name.lower().startswith(cand + " "):
            return name[len(cand):].strip()
    return name


# --------------------------------------------------------------------------- loaders
def _finish(df: pd.DataFrame, source: str) -> pd.DataFrame:
    for col in CANON_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    df["source"] = source
    return df[CANON_COLUMNS].reset_index(drop=True)


def _split_rows(names, makes, resolver):
    fam, var = [], []
    for make, rest in zip(makes, names):
        f, v = resolver.split(make, rest)
        fam.append(f)
        var.append(v)
    return fam, var


def load_cardekho_v3(path, resolver: FamilyResolver, source="cardekho_v3") -> pd.DataFrame:
    """'Car details v3.csv' and 'CAR DETAILS FROM CAR DEKHO.csv'. selling_price is already INR (verified in ingest)."""
    raw = pd.read_csv(path)
    makes, rests = [], []
    for name in raw["name"].astype(str):
        low = name.lower()
        first = name.split()[0]
        if low.startswith("land rover "):
            makes.append("Land Rover"); rests.append(name[len("land rover "):])
        elif low.startswith("opelcorsa"):          # typo in the source: 'OpelCorsa 1.4Gsi'
            makes.append("Opel"); rests.append("Corsa " + name[len("opelcorsa"):].strip())
        elif low.startswith("ashok leyland "):
            makes.append("Ashok Leyland"); rests.append(name[len("ashok leyland "):])
        else:
            makes.append(canon_make(first)); rests.append(name[len(first):].strip())
    fam, var = _split_rows(rests, makes, resolver)
    df = pd.DataFrame({
        "source_row": raw.index, "make": makes, "model_display": fam, "variant_display": var,
        "year": raw["year"], "km_driven": raw["km_driven"], "fuel": raw["fuel"].map(canon_fuel),
        "transmission": raw["transmission"].map(canon_transmission), "seller_type": raw["seller_type"].map(canon_seller),
        "owner_count": raw["owner"].map(owner_from_text), "price_inr": raw["selling_price"].astype(float),
    })
    if "engine" in raw:
        df["engine_cc"] = raw["engine"].map(parse_engine_cc)
        df["max_power_bhp"] = raw["max_power"].map(parse_power_bhp)
        df["mileage"] = raw["mileage"].map(parse_mileage)
        df["seats"] = pd.to_numeric(raw["seats"], errors="coerce")
    df["snapshot_year"] = np.nan  # filled in ingest from the verified source snapshot assumption
    return _finish(df, source)


def load_cardekho_v4(path, resolver: FamilyResolver) -> pd.DataFrame:
    raw = pd.read_csv(path)
    makes = raw["Make"].map(canon_make)
    fam, var = _split_rows(raw["Model"].astype(str), makes, resolver)
    df = pd.DataFrame({
        "source_row": raw.index, "make": makes, "model_display": fam, "variant_display": var,
        "year": raw["Year"], "km_driven": raw["Kilometer"], "fuel": raw["Fuel Type"].map(canon_fuel),
        "transmission": raw["Transmission"].map(canon_transmission), "seller_type": raw["Seller Type"].map(canon_seller),
        "owner_count": raw["Owner"].map(owner_from_text), "city": raw["Location"].map(canon_city),
        "engine_cc": raw["Engine"].map(parse_engine_cc), "max_power_bhp": raw["Max Power"].map(parse_power_bhp),
        "seats": pd.to_numeric(raw["Seating Capacity"], errors="coerce"), "price_inr": raw["Price"].astype(float),
    })
    return _finish(df, "cardekho_v4")


def load_city_listings(path, resolver: FamilyResolver) -> pd.DataFrame:
    """UsedCars_Combined.csv (city-wise listings). No transmission/owner columns: transmission is parsed
    from explicit tokens in the model name only; otherwise left unknown."""
    raw = pd.read_csv(path)
    makes = raw["brand"].map(canon_make)
    rests = [strip_make_prefix(n, m, rb) for n, m, rb in zip(raw["full_model_name"], makes, raw["brand"])]
    fam, var = _split_rows(rests, makes, resolver)
    df = pd.DataFrame({
        "source_row": raw.index, "make": makes, "model_display": fam, "variant_display": var,
        "year": raw["year"], "km_driven": raw["distance_travelled(kms)"], "fuel": raw["fuel_type"].map(canon_fuel),
        "transmission": [transmission_from_text(r) for r in rests], "city": raw["city"].map(canon_city),
        "price_inr": raw["price"].astype(float),
    })
    return _finish(df, "city_listings")


def load_third(path) -> pd.DataFrame:
    """Used_Car_Price_Prediction.csv. Excludes leakage / platform-only columns (broker_quote, original_price,
    emi_starts_from, booking_down_pymnt, car_rating, times_viewed, assured_buy, ...). Uses ad date for snapshot year."""
    raw = pd.read_csv(path)
    make = raw["make"].map(canon_make)
    model_key = raw["model"].astype(str).str.strip().str.lower().map(lambda s: _TRAILING_DISPLACEMENT.sub("", s))
    disp = [m.title() if not any(c.isdigit() for c in m) else m for m in model_key]
    ad_year = pd.to_datetime(raw["ad_created_on"], errors="coerce").dt.year
    df = pd.DataFrame({
        "source_row": raw.index, "make": make, "model_display": disp, "variant_display": raw["variant"].astype(str),
        "year": raw["yr_mfr"], "km_driven": raw["kms_run"], "fuel": raw["fuel_type"].map(canon_fuel),
        "transmission": raw["transmission"].map(canon_transmission), "owner_count": raw["total_owners"].astype(float).clip(upper=4),   # 4 == "4 or more", matching the CarDekho sources
        "city": raw["city"].map(canon_city), "body_type": raw["body_type"].map(canon_body),
        "price_inr": raw["sale_price"].astype(float), "snapshot_year": ad_year,
    })
    return _finish(df, "third_listings")


def load_cardekho_small_lakhs(path) -> pd.DataFrame:
    """'car data.csv': Selling_Price / Present_Price are in LAKHS (verified in ingest). Converted to INR here
    ONLY after verification; the file is used for unit verification and reporting, not for training
    (no make column, contains Present_Price which would leak the target)."""
    raw = pd.read_csv(path)
    return pd.DataFrame({"name": raw["Car_Name"], "year": raw["Year"], "price_inr": [to_inr(v, "lakh") for v in raw["Selling_Price"]],
                         "present_price_inr": [to_inr(v, "lakh") for v in raw["Present_Price"]]})


def norm_key(text) -> str:
    """Matching key for model/variant text: lower-case, hyphens and repeated spaces collapsed ('S-Cross' == 'S Cross')."""
    return re.sub(r"[\s\-]+", " ", str(text).strip().lower()).strip()


def pick_display(values: pd.Series, prefer_mask: pd.Series) -> str:
    """Most common casing among sources with proper casing; fall back to any."""
    pool = values[prefer_mask] if prefer_mask.any() else values
    return Counter(pool).most_common(1)[0][0]
