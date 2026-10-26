"""HTTP-level tests with FastAPI's TestClient. Skipped automatically when fastapi/httpx are not installed
(they could not be installed in the offline build environment, so these tests were WRITTEN BUT NOT EXECUTED there)."""
import tempfile, unittest
from pathlib import Path
from _paths import ARTIFACT_READY, MODELS, REPO

try:
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app
    HAVE = True
except Exception:  # pragma: no cover
    HAVE = False

BODY = {"make": "Maruti Suzuki", "model": "Swift", "year": 2016, "km_driven": 45000, "fuel": "Petrol", "transmission": "Manual"}
CID = "33333333-aaaa-bbbb-cccc-333333333333"; CID2 = "44444444-aaaa-bbbb-cccc-444444444444"


def make_client(models_dir=MODELS, **kw):
    tmp = tempfile.mkdtemp()
    s = Settings(models_dir=Path(models_dir), ml_dir=REPO / "ml", db_path=Path(tmp) / "h.sqlite3", frontend_dir=Path(tmp) / "none", **kw)
    return TestClient(create_app(s))


@unittest.skipUnless(HAVE, "fastapi/httpx not installed")
class NoModel(unittest.TestCase):
    def test_503_everywhere_and_no_fake_price(self):
        c = make_client(tempfile.mkdtemp())
        self.assertEqual(c.get("/api/health").json(), {"status": "model_unavailable", "model_loaded": False})
        r = c.post("/api/predict", json=BODY); self.assertEqual(r.status_code, 503); self.assertEqual(r.json()["error"]["code"], "model_unavailable")
        self.assertEqual(c.get("/api/metadata").status_code, 503)


@unittest.skipUnless(HAVE and ARTIFACT_READY, "needs fastapi and a trained model")
class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.c = make_client()

    def test_read_endpoints(self):
        for path in ("/api/health", "/api/metadata", "/api/vehicle-options", "/api/vehicle-options?make=Hyundai", "/api/model-metrics", "/api/analytics"):
            self.assertEqual(self.c.get(path).status_code, 200, path)
        self.assertEqual(self.c.get("/api/vehicle-options?make=Nope").status_code, 422)

    def test_predict_returns_numeric_inr(self):
        r = self.c.post("/api/predict", json=BODY); self.assertEqual(r.status_code, 200)
        j = r.json(); self.assertIsInstance(j["estimated_price_inr"], int); self.assertGreater(j["estimated_price_inr"], 0)

    def test_validation_errors(self):
        for bad in ({**BODY, "year": 1900}, {**BODY, "km_driven": -1}, {**BODY, "km_driven": "NaN"}, {**BODY, "extra": 1}, {k: v for k, v in BODY.items() if k != "fuel"}, {**BODY, "seats": 99}):
            r = self.c.post("/api/predict", json=bad); self.assertEqual(r.status_code, 422); self.assertEqual(r.json()["error"]["code"], "validation_error")

    def test_unsupported_vehicle_is_422_with_code(self):
        r = self.c.post("/api/predict", json={**BODY, "make": "Tesla"}); self.assertEqual((r.status_code, r.json()["error"]["code"]), (422, "unsupported_vehicle"))
        r = self.c.post("/api/predict", json={**BODY, "year": 2030}); self.assertEqual((r.status_code, r.json()["error"]["code"]), (422, "year_out_of_coverage"))

    def test_oversized_body_rejected(self):
        c = make_client(max_body_bytes=200); r = c.post("/api/predict", json={**BODY, "variant": "x" * 500}); self.assertEqual(r.status_code, 413)

    def test_history_is_private_per_client(self):
        self.c.post("/api/predict", json=BODY, headers={"X-Client-Id": CID})
        self.assertEqual(len(self.c.get("/api/history", headers={"X-Client-Id": CID}).json()["items"]), 1)
        self.assertEqual(self.c.get("/api/history", headers={"X-Client-Id": CID2}).json()["items"], [])
        self.assertEqual(self.c.get("/api/history").status_code, 400)
        self.assertEqual(self.c.delete("/api/history", headers={"X-Client-Id": CID}).json()["deleted"], 1)

    def test_errors_do_not_leak_internals(self):
        text = self.c.post("/api/predict", json={**BODY, "model": "zzz"}).text
        self.assertNotIn("Traceback", text); self.assertNotIn("/home", text)


if __name__ == "__main__":
    unittest.main()
