"""Unit tests for price units, INR formatting, parsing and canonicalisation.
Frames marked FIXTURE are tiny synthetic test fixtures; they are never used by the real training pipeline."""
import json, math, sys, tempfile, unittest
from pathlib import Path

ML = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML)); sys.path.insert(0, str(ML / "scripts"))

import pandas as pd
from ucpp import cleaning as C
from ucpp.units import format_inr, parse_engine_cc, parse_mileage, parse_power_bhp, to_inr


class PriceUnits(unittest.TestCase):
    def test_lakh_conversion_is_explicit(self):
        self.assertEqual(to_inr(5.5, "lakh"), 550_000)
        self.assertEqual(to_inr(3.35, "lakh"), 335_000)       # floating-point safe
        self.assertEqual(to_inr(1.25, "crore"), 12_500_000)

    def test_inr_values_are_never_rescaled(self):
        self.assertEqual(to_inr(450_000, "inr"), 450_000)

    def test_unknown_unit_and_non_finite_rejected(self):
        with self.assertRaises(ValueError): to_inr(5, "dollars")
        for bad in (float("nan"), float("inf")):
            with self.assertRaises(ValueError): to_inr(bad, "inr")

    def test_inr_formatting_indian_grouping(self):
        self.assertEqual(format_inr(85_000), "₹85,000")
        self.assertEqual(format_inr(345_000), "₹3,45,000")
        self.assertEqual(format_inr(1_250_000), "₹12,50,000")
        self.assertEqual(format_inr(12_500_000), "₹1,25,00,000")
        self.assertEqual(format_inr(999), "₹999")
        self.assertEqual(format_inr(-345_000), "-₹3,45,000")
        with self.assertRaises(ValueError): format_inr(float("nan"))


class Parsing(unittest.TestCase):
    def test_spec_parsers(self):
        self.assertEqual(parse_engine_cc("1248 CC"), 1248)
        self.assertEqual(parse_power_bhp("87 bhp @ 6000 rpm"), 87)
        self.assertEqual(parse_power_bhp("64@6200"), 64)
        self.assertEqual(parse_mileage("23.4 kmpl"), 23.4)
        self.assertEqual(parse_mileage("26.6 km/kg"), 26.6)

    def test_malformed_or_implausible_become_missing(self):
        for fn in (parse_engine_cc, parse_power_bhp, parse_mileage):
            self.assertIsNone(fn(None)); self.assertIsNone(fn("n/a")); self.assertIsNone(fn(float("nan")))
        self.assertIsNone(parse_engine_cc("5 CC")); self.assertIsNone(parse_power_bhp("99999 bhp"))


class Canonicalisation(unittest.TestCase):
    def test_makes_cities_fuel_owner_transmission(self):
        self.assertEqual(C.canon_make("Maruti"), "Maruti Suzuki"); self.assertEqual(C.canon_make("mercedes benz"), "Mercedes-Benz")
        self.assertEqual(C.canon_make("MINI"), "Mini")
        self.assertEqual(C.canon_city("bengaluru"), "Bengaluru"); self.assertEqual(C.canon_city("New Delhi"), "Delhi")
        self.assertEqual(C.canon_fuel("Petrol & CNG"), "CNG"); self.assertEqual(C.canon_fuel("petrol"), "Petrol"); self.assertEqual(C.canon_fuel("Petrol + 1"), "Other")
        self.assertEqual(C.owner_from_text("Fourth & Above Owner"), 4); self.assertEqual(C.owner_from_text("First"), 1)
        self.assertIsNone(C.owner_from_text("Test Drive Car")); self.assertIsNone(C.owner_from_text("UnRegistered Car"))
        self.assertEqual(C.transmission_from_text("Brio S MT"), "Manual"); self.assertEqual(C.transmission_from_text("City VX CVT"), "Automatic")
        self.assertIsNone(C.transmission_from_text("Swift VXI"))
        self.assertEqual(C.norm_key("S-Cross"), C.norm_key("S  Cross"))

    def test_model_family_split(self):
        third = pd.DataFrame({"make": ["maruti", "hyundai"], "model": ["swift dzire", "grand i10"]})   # FIXTURE
        r = C.FamilyResolver(C.build_families(third))
        self.assertEqual(r.split("Maruti Suzuki", "Swift Dzire VDI"), ("Swift Dzire", "VDI"))
        self.assertEqual(r.split("Honda", "City 2017-2020 EXi"), ("City", "EXi"))
        self.assertEqual(r.split("BMW", "3 Series 320d Prestige"), ("3 Series", "320d Prestige"))
        self.assertEqual(r.split("Hyundai", "Grand i10 Magna 1.2"), ("Grand i10", "Magna 1.2"))


class UnitVerification(unittest.TestCase):
    def test_lakh_source_is_detected_and_unknown_scale_refused(self):
        import ingest
        with tempfile.TemporaryDirectory() as d:                                  # FIXTURE files
            d = Path(d)
            pd.DataFrame({"Selling_Price": [3.6, 4.0, 3.2]}).to_csv(d / "small.csv", index=False)
            pd.DataFrame({"selling_price": [450000, 500000, 400000]}).to_csv(d / "v3.csv", index=False)
            out = ingest.verify_price_units({"cardekho_small_lakhs": d / "small.csv", "cardekho_v3": d / "v3.csv"}, 450000.0)
            self.assertEqual(out["cardekho_small_lakhs"]["verified_unit"], "lakh"); self.assertEqual(out["cardekho_v3"]["verified_unit"], "inr")
            pd.DataFrame({"selling_price": [4.5e9, 5e9]}).to_csv(d / "weird.csv", index=False)
            with self.assertRaises(SystemExit): ingest.verify_price_units({"cardekho_v3": d / "weird.csv"}, 450000.0)


class DataValidation(unittest.TestCase):
    def test_validator_flags_bad_records(self):
        import validate_data
        base = dict(row_id="a:1", source="s", group_id="g", make="Maruti Suzuki", model="swift", variant=None, year=2015, snapshot_year=2020, km_driven=40000,
                    fuel="Petrol", transmission="Manual", seller_type=None, owner_count=1, city=None, body_type="Hatchback", engine_cc=1197, max_power_bhp=80, mileage=20, seats=5, price_inr=400000)
        bad = pd.DataFrame([base, {**base, "row_id": "a:2", "price_inr": -5, "km_driven": 5_000_000, "year": 2030, "fuel": "Steam", "model": "swift2"}])   # FIXTURE
        with tempfile.TemporaryDirectory() as d:
            csv = Path(d) / "x.csv"; bad.to_csv(csv, index=False)
            failed = {c["check"] for c in validate_data.validate(csv, Path(d) / "r.json") if not c["passed"]}
        for expected in ("price >= ₹25,000", "km_driven within bounds", "year within bounds and not after snapshot", "fuel values valid"):
            self.assertIn(expected, failed)


if __name__ == "__main__":
    unittest.main()
