"""Tests against the REAL trained artifact and the REAL cleaned dataset (skipped if they have not been generated)."""
import json, sys, unittest
from pathlib import Path

ML = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML))
import numpy as np, pandas as pd

MODEL = ML / "models" / "used_car_price_model.joblib"
DATA = ML / "data" / "processed" / "used_cars_clean.csv"
READY = MODEL.exists() and DATA.exists() and (ML / "reports" / "split_assignment.csv").exists()


@unittest.skipUnless(READY, "run ml/scripts/ingest.py and train.py first")
class Artifact(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import joblib
        from ucpp.features import to_model_frame
        cls.model = joblib.load(MODEL)               # trusted: trained locally by train.py
        cls.df = pd.read_csv(DATA)
        cls.split = pd.read_csv(ML / "reports" / "split_assignment.csv")
        cls.metrics = json.loads((ML / "models" / "model_metrics.json").read_text(encoding="utf-8"))
        cls.to_frame = staticmethod(to_model_frame)
        test_ids = set(cls.split.loc[cls.split.split == "test", "row_id"])
        cls.test = cls.df[cls.df.row_id.isin(test_ids)].reset_index(drop=True)

    def test_predictions_on_real_rows_are_finite_positive_inr(self):
        p = self.model.predict(self.to_frame(self.test.head(200)))
        self.assertTrue(np.isfinite(p).all()); self.assertTrue((p > 0).all())
        self.assertTrue(1e4 < np.median(p) < 5e7, "median prediction should be in rupees, not lakhs")

    def test_unseen_categories_do_not_crash_and_stay_finite(self):
        row = self.test.head(1).copy()
        row["make"], row["model"], row["variant"], row["city"], row["body_type"] = "Zzz Motors", "unknown model", "x1", "Atlantis", "Hovercraft"
        p = self.model.predict(self.to_frame(row))
        self.assertTrue(np.isfinite(p).all() and p[0] > 0)

    def test_missing_optional_fields(self):
        row = self.test.head(1).copy()
        for c in ("variant", "seller_type", "city", "body_type", "owner_count", "engine_cc", "max_power_bhp", "mileage", "seats"):
            row[c] = np.nan
        p = self.model.predict(self.to_frame(row)); self.assertTrue(np.isfinite(p).all() and p[0] > 0)

    def test_target_inverse_transform_is_applied(self):
        X = self.to_frame(self.test.head(50))
        inner = self.model[-1].regressor_.predict(self.model[:-1].transform(X))
        self.assertTrue(np.allclose(np.expm1(inner), self.model.predict(X)))
        v = np.array([25_000., 550_000., 5e7]); self.assertTrue(np.allclose(np.expm1(np.log1p(v)), v))

    def test_age_is_derived_from_explicit_valuation_year(self):
        a = self.to_frame(self.test.head(1)); b = a.copy()
        b["year"] -= 5
        self.assertNotEqual(float(self.model.predict(a)[0]), float(self.model.predict(b)[0]))

    def test_no_group_leaks_between_dev_and_test(self):
        m = self.split.merge(self.df[["row_id", "group_id"]], on="row_id")
        self.assertFalse(set(m[m.split == "dev"].group_id) & set(m[m.split == "test"].group_id))

    def test_saved_metrics_are_consistent(self):
        m = self.metrics
        self.assertIn("INR", m["units"]); self.assertLess(m["test"]["mae_inr"], m["test_baseline_median"]["mae_inr"])
        self.assertEqual(m["split"]["n_test"] + m["split"]["n_dev"], m["split"]["n_total"])
        iv = m["interval"]; self.assertEqual(iv["validated"], abs(iv["test_coverage"] - iv["nominal_coverage"]) <= 0.05)
        for b in iv["bands"]:
            self.assertEqual(b["validated"], b["test_n"] >= 25 and abs(b["test_coverage"] - iv["nominal_coverage"]) <= 0.08)
        t = pd.read_csv(ML / "reports" / "test_predictions.csv")
        self.assertAlmostEqual(float((t.predicted_inr - t.actual_inr).abs().mean()), m["test"]["mae_inr"], delta=1.0)

    def test_no_leaky_columns_in_pipeline_inputs(self):
        schema = json.loads((ML / "models" / "feature_schema.json").read_text(encoding="utf-8"))
        banned = {"price_inr", "broker_quote", "original_price", "present_price", "emi_starts_from", "booking_down_pymnt", "inv_car_price", "std_invprice", "car_rating", "row_id", "group_id", "source"}
        self.assertFalse(banned & set(schema["pipeline_input_columns"]))

    def test_shipped_model_predicts_on_validated_representative_record(self):
        rep = pd.DataFrame([{
            "make": "Maruti Suzuki", "model": "swift", "variant": "vdi", "fuel": "Diesel",
            "transmission": "Manual", "seller_type": "Individual", "city": "Delhi", "body_type": "Hatchback",
            "year": 2016, "snapshot_year": 2022, "km_driven": 45000.0, "owner_count": 1.0,
            "engine_cc": 1248.0, "max_power_bhp": 74.0, "mileage": 22.9, "seats": 5.0,
        }])
        pred = self.model.predict(self.to_frame(rep))
        self.assertEqual(len(pred), 1)
        self.assertTrue(np.isfinite(pred[0]))
        self.assertTrue(200_000 < pred[0] < 800_000, f"Expected realistic INR estimate for 2016 Swift, got ₹{pred[0]:,.0f}")

    def test_valuation_date_policy_and_rejection_of_unsupported_years(self):
        schema = json.loads((ML / "models" / "feature_schema.json").read_text(encoding="utf-8"))
        valuation_year = schema["valuation_year"]
        self.assertEqual(valuation_year, 2022, "Historical valuation reference year must be explicitly 2022")
        from backend.app.services.model_service import ModelService, ServiceError
        svc = ModelService(ML / "models", ML)
        self.assertEqual(svc.valuation_year, 2022)
        # Verify years beyond training coverage are rejected with 422 year_out_of_coverage
        for unsupported_year in (2023, 2024, 2025, 2026):
            with self.assertRaises(ServiceError) as cm:
                svc.predict({"make": "Maruti Suzuki", "model": "Swift", "year": unsupported_year, "km_driven": 45000, "fuel": "Petrol", "transmission": "Manual"})
            self.assertEqual(cm.exception.code, "year_out_of_coverage")
            self.assertEqual(cm.exception.status, 422)

    def test_model_artifact_metadata_consistency(self):
        schema = json.loads((ML / "models" / "feature_schema.json").read_text(encoding="utf-8"))
        meta = json.loads((ML / "models" / "training_metadata.json").read_text(encoding="utf-8"))
        registry = json.loads((ML / "models" / "vehicle_registry.json").read_text(encoding="utf-8"))
        metrics = json.loads((ML / "models" / "model_metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["valuation_year"], meta["valuation_year"])
        self.assertEqual(schema["valuation_year"], registry["valuation_year"])
        self.assertEqual(meta["selected_estimator"], metrics["selected_model"])
        self.assertEqual(meta["data_version"], metrics["split"].get("data_version", meta["data_version"]))
        self.assertIn("INR", metrics["units"])

    def test_rupee_units_and_lakh_conversion_regression(self):
        from ucpp.units import format_inr, to_inr
        self.assertEqual(to_inr(5.5, "lakh"), 550_000.0)
        self.assertEqual(to_inr(0.25, "lakh"), 25_000.0)
        self.assertEqual(to_inr(1.0, "lakh"), 100_000.0)
        self.assertEqual(to_inr(1.5, "crore"), 15_000_000.0)
        self.assertEqual(format_inr(550_000), "₹5,50,000")
        self.assertEqual(format_inr(10_000_000), "₹1,00,00,000")


if __name__ == "__main__":
    unittest.main()
