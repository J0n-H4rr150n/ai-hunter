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

    # --- Target TLS ----------------------------------------------------------
    # Targets routinely present expired, self-signed or mismatched certificates.
    # For a security tool that is a finding to report, not a reason to refuse to
    # connect, so verification is off by default and the certificate is inspected
    # and recorded instead. VERIFY_TLS=true enforces it; TARGET_CA_BUNDLE points
    # at a lab CA to validate against that instead.
    VERIFY_TLS = os.getenv("VERIFY_TLS", "false").lower() == "true"
    TARGET_CA_BUNDLE = os.getenv("TARGET_CA_BUNDLE") or None

    @classmethod
    def requests_verify(cls):
        """Value for the `verify=` argument of a request against a target."""
        return cls.TARGET_CA_BUNDLE or cls.VERIFY_TLS

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

    # Measured floor for the served model. qwen38-27b-q8 streams at 8-12 tok/s on
    # this box; 4 is a pessimistic floor that still flags a genuinely stuck server.
    LLM_MIN_TOKENS_PER_SEC = float(os.getenv("LLM_MIN_TOKENS_PER_SEC", "4"))

    # Time to the *first* token covers prompt ingestion (a 20k-char DOM plus a
    # screenshot) and queueing behind another request — llama-server runs
    # --parallel 1, and a queued call was measured waiting 113s.
    LLM_FIRST_TOKEN_TIMEOUT = float(os.getenv("LLM_FIRST_TOKEN_TIMEOUT", "300"))

    # Once tokens are flowing the gap is ~0.1s, so a minute of silence means the
    # generation has died rather than slowed.
    LLM_STALL_TIMEOUT = float(os.getenv("LLM_STALL_TIMEOUT", "60"))

    @classmethod
    def llm_total_timeout(cls) -> float:
        """
        Realistic ceiling for one call, derived rather than guessed:
        the whole token budget at the pessimistic floor rate, plus the
        first-token allowance. At the defaults (4096 tokens, 4 tok/s, 300s)
        that is ~1324s — comfortably above the ~340s a full-length answer
        actually takes at the measured 12 tok/s.
        """
        override = os.getenv("LLM_TOTAL_TIMEOUT")
        if override:
            return float(override)
        return (cls.LLM_MAX_TOKENS / cls.LLM_MIN_TOKENS_PER_SEC) + cls.LLM_FIRST_TOKEN_TIMEOUT

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
