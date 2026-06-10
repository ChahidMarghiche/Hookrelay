import os
from dataclasses import dataclass


@dataclass
class Settings:
    database_path: str = os.environ.get("HOOKRELAY_DB", "hookrelay.db")
    delivery_timeout_seconds: float = float(os.environ.get("HOOKRELAY_DELIVERY_TIMEOUT", "10"))
    retry_base_delay_seconds: float = float(os.environ.get("HOOKRELAY_RETRY_BASE_DELAY", "10"))
    worker_interval_seconds: float = float(os.environ.get("HOOKRELAY_WORKER_INTERVAL", "5"))


settings = Settings()
