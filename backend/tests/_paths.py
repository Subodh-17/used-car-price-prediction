import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[2]
for p in (REPO / "backend", REPO / "ml"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
MODELS = REPO / "ml" / "models"
ARTIFACT_READY = (MODELS / "used_car_price_model.joblib").exists()
