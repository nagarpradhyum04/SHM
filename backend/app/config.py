"""Application configuration, loaded from environment variables (prefix ``SS_``).

See ``backend/.env.example`` for every supported setting. Secrets (device keys)
must never be committed to source control.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SS_", env_file=BACKEND_DIR / ".env", extra="ignore", protected_namespaces=("settings_",))

    app_name: str = "StructuraSense AI"
    environment: str = "development"

    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'structurasense.db').as_posix()}"
    storage_dir: Path = BACKEND_DIR / "data" / "storage"
    model_dir: Path = BACKEND_DIR / "model_store"

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])

    max_upload_mb: float = 15.0
    allowed_image_types: list[str] = Field(default_factory=lambda: ["image/jpeg", "image/png", "image/bmp", "image/webp"])
    max_image_pixels: int = 40_000_000

    # Device ingestion security. When true, every ingestion request must carry
    # a valid per-device token (issued at registration) or the shared key below.
    device_auth_required: bool = True
    device_shared_key: str | None = None
    max_readings_per_request: int = 2000

    # Background loop (device status checks, live simulation, feature extraction)
    background_enabled: bool = True
    background_interval_s: float = 5.0

    seed_demo_data: bool = True
    auto_migrate: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
