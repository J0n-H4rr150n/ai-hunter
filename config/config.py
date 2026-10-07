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
    # Qwen3 spends a large share of its budget on reasoning before the answer
    # starts, so a small cap truncates mid-thought and yields an empty completion.
    LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
    # Qwen3 supports disabling its thinking phase. Leaving it on preserves quality;
    # turning it off is markedly faster and avoids reasoning eating the whole budget,
    # which matters most for strict-JSON calls.
    LLM_ENABLE_THINKING = os.getenv("LLM_ENABLE_THINKING", "true").lower() == "true"
    # Independently of the above, skip thinking for JSON responses, where the answer
    # is a structured object rather than an argument.
    LLM_THINK_ON_JSON = os.getenv("LLM_THINK_ON_JSON", "false").lower() == "true"

    # --- Timeouts -------------------------------------------------------------
    # A local 27B at Q8 runs at single-digit tokens/second, so a long answer can
    # legitimately take many minutes. Responses are streamed, which means the only
    # deadline that matters is the gap *between* tokens, not the total duration:
    # a slow model is not an error, a dead one is.
    LLM_STREAM = os.getenv("LLM_STREAM", "true").lower() == "true"
    # Connecting should be instant on localhost; failing fast here is useful.
    LLM_CONNECT_TIMEOUT = float(os.getenv("LLM_CONNECT_TIMEOUT", "15"))
    # Max silence between tokens before we call the server dead. Generous enough to
    # cover prompt ingestion of a large context plus a screenshot.
    LLM_STALL_TIMEOUT = float(os.getenv("LLM_STALL_TIMEOUT", "600"))
    # Optional overall ceiling. 0 means no limit, which is the default: the model is
    # as slow as it is, and cutting a generation off mid-answer helps nobody.
    LLM_TOTAL_TIMEOUT = float(os.getenv("LLM_TOTAL_TIMEOUT", "0"))
    # How often to report "still generating" while waiting.
    LLM_PROGRESS_INTERVAL = float(os.getenv("LLM_PROGRESS_INTERVAL", "20"))

    LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
    LLM_RETRY_DELAY = float(os.getenv("LLM_RETRY_DELAY", "2"))

    @staticmethod
    def ensure_dirs():
        """Ensure critical directories exist."""
        os.makedirs(Config.SHADOW_LOG_DIR, exist_ok=True)
        os.makedirs(Config.HIVE_BUCKET_ROOT / "logs", exist_ok=True)

# Auto-execute directory creation on import for convenience
Config.ensure_dirs()
