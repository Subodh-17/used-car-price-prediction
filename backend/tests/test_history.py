import tempfile, unittest
from pathlib import Path
import _paths  # noqa: F401
from app.services.history import HistoryStore

A, B = "11111111-aaaa-bbbb-cccc-111111111111", "22222222-aaaa-bbbb-cccc-222222222222"


class History(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.store = HistoryStore(Path(self.tmp.name) / "h.sqlite3", "salt", limit=3)
    def tearDown(self): self.tmp.cleanup()

    def test_users_cannot_see_each_others_history(self):
        self.store.add(A, "m@1", {"make": "X"}, 500000, 400000, 600000); self.store.add(B, "m@1", {"make": "Y"}, 300000, None, None)
        self.assertEqual([i["inputs"]["make"] for i in self.store.list(A)], ["X"]); self.assertEqual([i["inputs"]["make"] for i in self.store.list(B)], ["Y"])
        self.assertEqual(self.store.clear(A), 1); self.assertEqual(self.store.list(A), []); self.assertEqual(len(self.store.list(B)), 1)

    def test_limit_and_ordering(self):
        for i in range(5): self.store.add(A, "m", {"n": i}, 1000 + i, None, None)
        items = self.store.list(A); self.assertEqual([i["inputs"]["n"] for i in items], [4, 3, 2])

    def test_client_ids_are_hashed_and_validated(self):
        self.store.add(A, "m", {}, 1.0, None, None)
        import sqlite3
        conn = sqlite3.connect(self.store.path)
        try:
            rows = conn.execute("SELECT client_hash FROM predictions").fetchall()
        finally:
            conn.close()
        self.assertNotIn(A, rows[0][0]); self.assertEqual(len(rows[0][0]), 64)
        for bad in (None, "", "short", "has spaces in the id........", "x" * 100, "../../etc/passwd--------"): self.assertFalse(HistoryStore.valid_client_id(bad))
        self.assertTrue(HistoryStore.valid_client_id(A))

    def test_only_expected_columns_are_stored(self):
        import sqlite3
        conn = sqlite3.connect(self.store.path)
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(predictions)").fetchall()]
        finally:
            conn.close()
        self.assertEqual(set(cols), {"id", "client_hash", "created_utc", "model_version", "inputs_json", "estimate_inr", "low_inr", "high_inr"})


if __name__ == "__main__":
    unittest.main()
