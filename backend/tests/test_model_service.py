"""Inference-service tests. Real-model tests use the trained artifact; STUB classes are test fixtures only."""
import copy, tempfile, unittest
from pathlib import Path
import numpy as np

from _paths import ARTIFACT_READY, MODELS, REPO
from app.services.model_service import ModelService, ServiceError

BASE = {"make": "Maruti Suzuki", "model": "Swift", "year": 2016, "km_driven": 45000, "fuel": "Petrol", "transmission": "Manual"}


class StubPipeline:                      # TEST FIXTURE: returns whatever it was told to
    def __init__(self, value): self.value = value
    def predict(self, X): return np.full(len(X), self.value, dtype=float)


class OutputValidation(unittest.TestCase):
    def test_invalid_outputs_are_rejected_not_clamped(self):
        for bad in (np.array([np.nan]), np.array([np.inf]), np.array([-np.inf]), np.array([-5.0]), np.array([0.0]), np.array([1.0, 2.0]), np.array([])):
            with self.assertRaises(ServiceError) as cm: ModelService._validate_output(bad)
            self.assertEqual(cm.exception.code, "invalid_prediction"); self.assertEqual(cm.exception.status, 500)
        self.assertEqual(ModelService._validate_output(np.array([123456.7])), 123456.7)


class MissingArtifact(unittest.TestCase):
    def test_service_unavailable_never_fakes_a_price(self):
        with tempfile.TemporaryDirectory() as d:
            svc = ModelService(d, REPO / "ml")
            self.assertFalse(svc.ready); self.assertEqual(svc.health(), {"status": "model_unavailable", "model_loaded": False})
            for call in (lambda: svc.predict(BASE), svc.metadata, svc.vehicle_options, svc.metrics_view):
                with self.assertRaises(ServiceError) as cm: call()
                self.assertEqual(cm.exception.status, 503); self.assertEqual(cm.exception.code, "model_unavailable")
                self.assertNotIn(str(d), cm.exception.message)           # no local paths leaked


@unittest.skipUnless(ARTIFACT_READY, "train the model first")
class RealModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.svc = ModelService(MODELS, REPO / "ml")

    def test_health_metadata_options(self):
        self.assertEqual(self.svc.health(), {"status": "ok", "model_loaded": True})
        md = self.svc.metadata(); self.assertGreater(md["coverage"]["rows"], 1000); self.assertEqual(md["limits"]["max_year"], md["model"]["valuation_year"])
        opts = self.svc.vehicle_options(); self.assertTrue(opts["makes"]); self.assertIn("Petrol", opts["fuels"])
        self.assertNotIn("/", str(md))                                    # no filesystem paths

    def test_models_depend_on_manufacturer(self):
        maruti = {m["name"] for m in self.svc.vehicle_options("Maruti Suzuki")["models"]}
        hyundai = {m["name"] for m in self.svc.vehicle_options("hyundai")["models"]}      # case-insensitive
        self.assertIn("Swift", maruti); self.assertNotIn("Swift", hyundai); self.assertIn("Creta", hyundai)
        detail = self.svc.vehicle_options("Maruti Suzuki", "Swift")["model"]; self.assertTrue(detail["variants"])
        with self.assertRaises(ServiceError): self.svc.vehicle_options("Maruti Suzuki", "Creta")

    def test_successful_real_prediction(self):
        r = self.svc.predict(dict(BASE))
        self.assertIsInstance(r["estimated_price_inr"], int); self.assertTrue(50_000 < r["estimated_price_inr"] < 2_000_000)
        iv = r["interval"]; self.assertIsNotNone(iv); self.assertIn("price_band", iv); self.assertLess(iv["low_inr"], r["estimated_price_inr"]); self.assertGreater(iv["high_inr"], r["estimated_price_inr"])
        self.assertEqual(r["warnings"], []); self.assertTrue(r["explanation"]["effects"]); self.assertIn("not a guaranteed", r["disclaimer"].lower())
        self.assertEqual(r["model"]["valuation_year"], self.svc.valuation_year)

    def test_input_is_not_mutated_and_prediction_is_deterministic(self):
        p = dict(BASE); before = copy.deepcopy(p)
        a, b = self.svc.predict(p), self.svc.predict(p)
        self.assertEqual(p, before); self.assertEqual(a["estimated_price_inr"], b["estimated_price_inr"])

    def test_newer_same_car_is_worth_more(self):
        new = self.svc.predict({**BASE, "year": 2020, "km_driven": 20000})["estimated_price_inr"]
        old = self.svc.predict({**BASE, "year": 2010, "km_driven": 120000})["estimated_price_inr"]
        self.assertGreater(new, old)

    def test_unsupported_vehicles_are_rejected_honestly(self):
        for payload, field in (({**BASE, "make": "Tesla"}, "make"), ({**BASE, "model": "Cybertruck"}, "model")):
            with self.assertRaises(ServiceError) as cm: self.svc.predict(payload)
            self.assertEqual(cm.exception.code, "unsupported_vehicle"); self.assertEqual(cm.exception.status, 422); self.assertEqual(cm.exception.details["field"], field)

    def test_year_beyond_training_coverage_is_rejected(self):
        with self.assertRaises(ServiceError) as cm: self.svc.predict({**BASE, "year": self.svc.valuation_year + 1})
        self.assertEqual(cm.exception.code, "year_out_of_coverage")

    def test_unsupported_category_values(self):
        for k, v in (("fuel", "Steam"), ("transmission", "Telepathic"), ("body_type", "Hovercraft")):
            with self.assertRaises(ServiceError) as cm: self.svc.predict({**BASE, k: v})
            self.assertEqual(cm.exception.code, "unsupported_value")

    def test_unseen_variant_and_city_produce_warnings_not_silent_mapping(self):
        r = self.svc.predict({**BASE, "variant": "Totally Made Up Trim", "city": "Atlantis"})
        codes = {w["code"] for w in r["warnings"]}; self.assertIn("variant_unseen", codes); self.assertIn("city_unsupported", codes)
        self.assertIsNone(r["inputs_used"]["city"]); self.assertGreater(r["estimated_price_inr"], 0)

    def test_fuel_not_offered_for_model_warns(self):
        r = self.svc.predict({**BASE, "fuel": "Electric"})
        self.assertIn("fuel_unseen_for_model", {w["code"] for w in r["warnings"]})

    def test_very_old_car_and_extreme_mileage(self):
        old = self.svc.predict({**BASE, "year": 1990, "km_driven": 150000})
        self.assertGreater(old["estimated_price_inr"], 0); self.assertIn("year_outside_model_range", {w["code"] for w in old["warnings"]})
        hi = self.svc.predict({**BASE, "km_driven": 900000})
        self.assertIn("km_above_typical", {w["code"] for w in hi["warnings"]}); self.assertGreater(hi["estimated_price_inr"], 0)

    def test_missing_optional_fields(self):
        r = self.svc.predict({**BASE, "variant": None, "owner_count": None, "engine_cc": None, "city": None, "seller_type": None, "body_type": None})
        self.assertGreater(r["estimated_price_inr"], 0)

    def test_luxury_vehicle_near_distribution_edge(self):
        r = self.svc.predict({"make": "Mercedes-Benz", "model": "E-Class", "year": 2019, "km_driven": 30000, "fuel": "Diesel", "transmission": "Automatic"})
        self.assertGreater(r["estimated_price_inr"], 1_500_000)
        if r["estimated_price_inr"] > self.svc.registry["ranges"]["price_inr_p95"]:
            self.assertTrue({"high_price_band", "extreme_price_band"} & {w["code"] for w in r["warnings"]})

    def test_rare_make_flags_limited_data(self):
        rare = next(m for m in self.svc.registry["makes"] if m["limited"])
        entry = self.svc.registry["models"][rare["name"]][0]
        r = self.svc.predict({"make": rare["name"], "model": entry["name"], "year": entry["year_max"], "km_driven": 30000,
                              "fuel": entry["fuels"][0], "transmission": (entry["transmissions"] or ["Manual"])[0]})
        self.assertIn("limited_make_data", {w["code"] for w in r["warnings"]})

    def test_invalid_model_output_surfaces_as_error(self):
        svc = ModelService(MODELS, REPO / "ml")
        for bad in (np.nan, np.inf, -1000.0):
            svc.pipeline = StubPipeline(bad)                      # TEST FIXTURE
            with self.assertRaises(ServiceError) as cm: svc.predict(dict(BASE))
            self.assertEqual(cm.exception.code, "invalid_prediction")

    def test_interval_hidden_for_unvalidated_price_band(self):
        svc = ModelService(MODELS, REPO / "ml"); iv = svc.metrics["interval"]
        bands = [dict(b, validated=False) for b in iv["bands"]]; svc.metrics = {**svc.metrics, "interval": {**iv, "bands": bands}}
        r = svc.predict(dict(BASE)); self.assertIsNone(r["interval"]); self.assertIn("not available for estimates", r["interval_note"])

    def test_unvalidated_interval_is_hidden(self):
        svc = ModelService(MODELS, REPO / "ml"); svc.metrics = {**svc.metrics, "interval": {**svc.metrics["interval"], "validated": False}}
        r = svc.predict(dict(BASE)); self.assertIsNone(r["interval"]); self.assertIn("single estimate", r["interval_note"])

    def test_missing_artifacts_distinguished_from_corrupt_artifact(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            # 1. Missing files
            svc_missing = ModelService(p, REPO / "ml")
            self.assertFalse(svc_missing.ready)
            self.assertIn("not found", svc_missing.load_error.lower())

            # 2. Files present but corrupt joblib
            for f in ("vehicle_registry.json", "model_metrics.json", "feature_schema.json", "training_metadata.json"):
                (p / f).write_text("{}", encoding="utf-8")
            (p / "used_car_price_model.joblib").write_bytes(b"corrupted binary data")
            svc_corrupt = ModelService(p, REPO / "ml")
            self.assertFalse(svc_corrupt.ready)
            self.assertIn("could not be loaded", svc_corrupt.load_error.lower())

    def test_sparse_variant_observation_warning(self):
        # Find a model with a variant with count < 5
        found = None
        for make, models in self.svc.registry["models"].items():
            for m in models:
                sparse = [v for v in m.get("variants", []) if 0 < v.get("count", 0) < 5]
                if sparse:
                    found = (make, m["name"], sparse[0]["name"])
                    break
            if found:
                break
        if found:
            mk, md, vr = found
            r = self.svc.predict({**BASE, "make": mk, "model": md, "variant": vr})
            codes = {w["code"] for w in r["warnings"]}
            self.assertIn("limited_variant_data", codes)

    def test_historical_reference_and_freshness_metadata(self):
        r = self.svc.predict(dict(BASE))
        m = r["model"]
        self.assertEqual(m["valuation_year"], 2022)
        self.assertEqual(m["historical_reference_year"], 2022)
        self.assertTrue(m["is_historical"])
        self.assertIn("2022", m["valuation_reference_note"])

    def test_only_supported_body_types_in_registry(self):
        body_types = self.svc.registry["body_types"]
        self.assertEqual(set(body_types), {"Hatchback", "Sedan", "SUV"})
        for unsupp in ("Coupe", "Convertible", "Wagon", "Van", "Pickup"):
            self.assertNotIn(unsupp, body_types)


if __name__ == "__main__":
    unittest.main()
