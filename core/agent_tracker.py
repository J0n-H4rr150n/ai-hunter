import os
import time
import uuid
import json
from datetime import datetime
from PIL import Image
from io import BytesIO
from pathlib import Path
from config.config import Config
from typing import Optional, Any

class AgentTracker:
    """
    Tracks agent activity and handles 'shadowing' operations like 
    screenshot capture and state logging into the hive bucket.
    
    When a browser instance (SoMBrowser) is provided, screenshots are
    captured from the active browser page. Otherwise, no screenshots
    are taken (metadata only).
    """

    def __init__(self, agent_id=None, browser=None):
        self.agent_id = agent_id or f"agent_{str(uuid.uuid4())[:8]}"
        self.session_start = datetime.now()
        self.browser = browser  # Optional SoMBrowser instance
        
        # Construct the Hive Bucket Path
        # Structure: hive_bucket/screenshots/YYYY-MM-DD/<agent_id>/
        # This prevents a flat directory from becoming unmanageable.
        date_str = self.session_start.strftime("%Y-%m-%d")
        self.write_path = Config.SHADOW_LOG_DIR / date_str / self.agent_id
        
        self._ensure_storage()

    def _ensure_storage(self):
        """Ensures the specific hive path for this session exists."""
        if not os.path.exists(self.write_path):
            os.makedirs(self.write_path, exist_ok=True)

    def set_browser(self, browser):
        """
        Sets or updates the browser instance for screenshot capture.
        
        Args:
            browser: SoMBrowser instance
        """
        self.browser = browser

    def capture_shadow(self, step_name="action", metadata=None):
        """
        Captures a screenshot ('shadow') of the current state.
        
        If a browser is available, captures the browser page.
        Otherwise, only saves metadata without screenshots.
        
        Args:
            step_name (str): A label for the step (e.g., 'click_button', 'search').
            metadata (dict): Optional dictionary of extra data to log alongside the image.
        
        Returns:
            str: The filepath of the saved screenshot, or None if no browser available.
        """
        timestamp = datetime.now().strftime("%H-%M-%S-%f")[:-3]
        
        # Always save metadata
        if metadata:
            self._save_metadata(timestamp, step_name, metadata)

        # Only capture screenshots if browser is available
        if not self.browser:
            if Config.DEBUG:
                print(f"[Tracker] Metadata logged (no browser): {step_name}")
            return None

        filename = f"{timestamp}_{step_name}.png"
        filepath = self.write_path / filename

        try:
            # Capture from browser page
            screenshot_bytes = self.browser.page.screenshot(type="png")
            
            # Save the screenshot
            img = Image.open(BytesIO(screenshot_bytes))
            img.save(filepath)

            if Config.DEBUG:
                print(f"[Tracker] Shadow captured: {filepath}")

            return str(filepath)

        except Exception as e:
            print(f"[Tracker] Failed to capture browser screenshot: {e}")
            return None

    def _save_metadata(self, timestamp, step_name, data):
        """Saves a JSON sidecar file for the screenshot."""
        meta_filename = f"{timestamp}_{step_name}.json"
        meta_filepath = self.write_path / meta_filename
        
        entry = {
            "timestamp": timestamp,
            "agent_id": self.agent_id,
            "step": step_name,
            "data": data
        }
        
        with open(meta_filepath, 'w') as f:
            json.dump(entry, f, indent=2)

    def get_session_path(self):
        """Returns the current active directory in the hive."""
        return str(self.write_path)