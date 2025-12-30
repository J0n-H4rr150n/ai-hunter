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
    HIVE_BUCKET_ROOT = BASE_DIR / "hive_bucket"
    
    # Shadow Log Directory (Screenshots)
    # Storing screenshots in the hive structure rather than flat logs
    SHADOW_LOG_DIR = HIVE_BUCKET_ROOT / "screenshots"

    # General Settings
    DEBUG = True
    keep_alive = False

    @staticmethod
    def ensure_dirs():
        """Ensure critical directories exist."""
        os.makedirs(Config.SHADOW_LOG_DIR, exist_ok=True)
        os.makedirs(Config.HIVE_BUCKET_ROOT / "logs", exist_ok=True)

# Auto-execute directory creation on import for convenience
Config.ensure_dirs()