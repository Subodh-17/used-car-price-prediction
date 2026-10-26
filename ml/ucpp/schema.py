"""Single source of truth for feature definitions, bounds and display vocabularies."""
from __future__ import annotations

CATEGORICAL_FEATURES = ["make", "model", "variant", "fuel", "transmission", "seller_type", "city", "body_type"]
NUMERIC_FEATURES = ["vehicle_age", "km_driven", "owner_count", "engine_cc", "max_power_bhp", "mileage", "seats"]
# Columns the saved pipeline expects as input (vehicle_age is derived inside the pipeline).
PIPELINE_INPUT_COLUMNS = (
    ["make", "model", "variant", "fuel", "transmission", "seller_type", "city", "body_type"]
    + ["year", "snapshot_year", "km_driven", "owner_count", "engine_cc", "max_power_bhp", "mileage", "seats"]
)
TARGET = "price_inr"

FUELS = ["Petrol", "Diesel", "CNG", "LPG", "Electric", "Hybrid", "Other"]
TRANSMISSIONS = ["Manual", "Automatic"]
BODY_TYPES = ["Hatchback", "Sedan", "SUV"]
SELLER_TYPES = ["Individual", "Dealer", "Trustmark Dealer", "Corporate", "Commercial Registration"]

# Hard sanity bounds (data validation + API validation).
BOUNDS = {
    "year": (1980, 2100),
    "km_driven": (0, 1_000_000),
    "owner_count": (1, 4),   # 4 means "4 or more"
    "engine_cc": (300, 9000),
    "max_power_bhp": (15, 1500),
    "mileage": (2, 60),
    "seats": (2, 14),
}
MIN_PRICE_INR = 25_000          # below this a listing is treated as an implausible target
MAX_KM = 1_000_000
MAX_KM_PER_YEAR = 100_000       # for age >= 1
MIN_YEAR = 1980

# Coverage thresholds used by the API.
MIN_MODEL_ROWS = 5              # (make, model) with fewer rows -> "limited coverage" warning
MIN_MAKE_ROWS = 30              # make with fewer rows -> "limited coverage" warning
MIN_CITY_ROWS = 30              # cities with fewer rows are not offered / not used
MIN_VARIANT_ROWS = 5            # variant with fewer rows -> "limited coverage" warning
