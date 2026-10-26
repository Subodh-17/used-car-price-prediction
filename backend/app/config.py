"""Environment-based configuration (no secrets are required or hard-coded)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    ml_dir: Path = REPO_ROOT / "ml"
    models_dir: Path = REPO_ROOT / "ml" / "models"
    db_path: Path = REPO_ROOT / "backend" / "data" / "history.sqlite3"
    frontend_dir: Path = REPO_ROOT / "frontend"
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:8000", "http://127.0.0.1:8000", "http://localhost:5173"])
    max_body_bytes: int = 16_384
    predict_timeout_s: float = 10.0
    history_limit: int = 100
    history_salt: str = "change-me"          # set HISTORY_SALT in production
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        e = os.environ
        base = cls()
        salt = e.get("HISTORY_SALT", base.history_salt)
        is_prod = e.get("ENVIRONMENT", "").lower() == "production" or e.get("ENV", "").lower() == "production"
        if is_prod and (not salt or salt in {"change-me", "replace-with-a-long-random-string"}):
            raise ValueError("HISTORY_SALT must be configured to a secure, random string in production.")
        return cls(
            ml_dir=Path(e.get("ML_DIR", base.ml_dir)),
            models_dir=Path(e.get("MODELS_DIR", base.models_dir)),
            db_path=Path(e.get("HISTORY_DB_PATH", base.db_path)),
            frontend_dir=Path(e.get("FRONTEND_DIR", base.frontend_dir)),
            cors_origins=_split(e["CORS_ORIGINS"]) if "CORS_ORIGINS" in e else base.cors_origins,
            max_body_bytes=int(e.get("MAX_BODY_BYTES", base.max_body_bytes)),
            predict_timeout_s=float(e.get("PREDICT_TIMEOUT_S", base.predict_timeout_s)),
            history_limit=int(e.get("HISTORY_LIMIT", base.history_limit)),
            history_salt=salt,
            log_level=e.get("LOG_LEVEL", base.log_level),
        )
