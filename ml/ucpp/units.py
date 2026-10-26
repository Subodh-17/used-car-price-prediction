"""Price-unit handling, INR formatting and parsing of textual specification fields.

All internal prices are plain numeric INR (rupees). A source's prices are converted
only when its unit has been *verified* (see ``verify_price_unit`` in ingest).
"""
from __future__ import annotations

import math
import re

LAKH = 100_000
CRORE = 10_000_000
_UNIT_FACTORS = {"inr": 1, "rupee": 1, "rupees": 1, "lakh": LAKH, "lakhs": LAKH, "lac": LAKH, "crore": CRORE}


def to_inr(value: float, unit: str) -> float:
    """Convert ``value`` expressed in ``unit`` (inr / lakh / crore) to whole rupees."""
    try:
        factor = _UNIT_FACTORS[unit.strip().lower()]
    except KeyError as exc:
        raise ValueError(f"Unknown price unit: {unit!r}") from exc
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Price must be finite")
    return float(round(value * factor))


def format_inr(value: float) -> str:
    """Format a rupee amount with Indian digit grouping, e.g. 345000 -> '₹3,45,000'."""
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Cannot format a non-finite amount")
    negative = value < 0
    digits = str(int(round(abs(value))))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join(groups + [tail])
    return f"{'-' if negative else ''}₹{digits}"


_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")


def first_number(text) -> float | None:
    """Return the first number found in ``text`` or None."""
    if text is None or (isinstance(text, float) and math.isnan(text)):
        return None
    m = _NUM.search(str(text).replace(",", ""))
    return float(m.group()) if m else None


def parse_engine_cc(text) -> float | None:
    v = first_number(text)
    return v if v is not None and 300 <= v <= 9000 else None


def parse_power_bhp(text) -> float | None:
    """'74 bhp', '87 bhp @ 6000 rpm', '64@6200' -> first number (bhp)."""
    v = first_number(text)
    return v if v is not None and 15 <= v <= 1500 else None


def parse_mileage(text) -> float | None:
    """'23.4 kmpl' / '26.6 km/kg' -> number. Unit (kmpl vs km/kg) differs by fuel; see docs."""
    v = first_number(text)
    return v if v is not None and 2 <= v <= 60 else None
