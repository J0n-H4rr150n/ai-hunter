import os
from pathlib import Path

class Config:
    """
    Project Configuration
    """
    # Base directory of the project
    BASE_DIR = Path(__file__).resolve().parent.parent

    # Hive Storage Configuration
    # Changing shadow logs to the local hive-structured bucket
    HIVE_BUCKET_ROOT = Path(os.getenv("HIVE_BUCKET_PATH", BASE_DIR / "hive_bucket"))

    # Shadow Log Directory (Screenshots)
    # Storing screenshots in the hive structure rather than flat logs
    SHADOW_LOG_DIR = HIVE_BUCKET_ROOT / "screenshots"

    # General Settings
    DEBUG = True
    keep_alive = False

    # --- Local LLM (llama.cpp / llama-server) ---------------------------------
    # OpenAI-compatible endpoint. Nothing leaves this host.
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:30087/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "qwen38-27b-q8")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "local")

    # Qwen3.8-27B is served with a vision projector, so screenshots are usable.
    LLM_SUPPORTS_VISION = os.getenv("LLM_SUPPORTS_VISION", "true").lower() == "true"

    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.4"))
    LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))
    # Generous: a 27B at Q8 with a screenshot attached is not fast.
    LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "300"))
    LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
    LLM_RETRY_DELAY = float(os.getenv("LLM_RETRY_DELAY", "2"))

    @staticmethod
    def ensure_dirs():
        """Ensure critical directories exist."""
        os.makedirs(Config.SHADOW_LOG_DIR, exist_ok=True)
        os.makedirs(Config.HIVE_BUCKET_ROOT / "logs", exist_ok=True)

# Auto-execute directory creation on import for convenience
Config.ensure_dirs()
