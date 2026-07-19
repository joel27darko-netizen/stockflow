"""
Application configuration.

Centralizes all environment-driven settings using pydantic-settings so
that the rest of the codebase never touches os.environ directly.
"""
from pydantic_settings import BaseSettings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    app_name: str = "StockFlow"
    secret_key: str = "CHANGE_ME_IN_PRODUCTION_super_secret_key_12345"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8  # 8 hour session

    database_url: str = f"sqlite:///{BASE_DIR}/stockflow.db"

    low_stock_default_reorder_level: int = 10

    qr_code_dir: Path = BASE_DIR / "app" / "static" / "qrcodes"
    barcode_dir: Path = BASE_DIR / "app" / "static" / "barcodes"
    product_image_dir: Path = BASE_DIR / "app" / "static" / "product_images"

    class Config:
        env_file = ".env"


settings = Settings()

# Ensure required directories exist at import time.
settings.qr_code_dir.mkdir(parents=True, exist_ok=True)
settings.barcode_dir.mkdir(parents=True, exist_ok=True)
settings.product_image_dir.mkdir(parents=True, exist_ok=True)
