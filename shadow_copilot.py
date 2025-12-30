import time
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from config.config import Config

class ShadowCopilot:
    """
    A standalone tool to monitor an active agent session in real-time.
    It watches the Hive Bucket for new 'shadow' (screenshot) metadata 
    and streams the agent's activity to this console.
    """
    
    def __init__(self):
        self.root_dir = Config.SHADOW_LOG_DIR
        self.current_session_dir = None
        self.known_files = set()
        self.live_view = False

    def find_latest_session(self):
        """Locates the most recently modified agent session directory."""
        # 1. Find today's date folder
        # (For simplicity, we look for the most recent date folder if today's is empty)
        if not self.root_dir.exists():
            return None

        # Get all date directories
        date_dirs = sorted([d for d in self.root_dir.iterdir() if d.is_dir()], 
                           key=lambda x: x.name, reverse=True)
        
        if not date_dirs:
            return None

        # Look inside the most recent date dir for agent folders
        latest_date_dir = date_dirs[0]
        
        # Get agent dirs sorted by modification time
        agent_dirs = sorted([d for d in latest_date_dir.iterdir() if d.is_dir()],
                            key=lambda x: x.stat().st_mtime, reverse=True)
        
        if not agent_dirs:
            return None
            
        return agent_dirs[0]

    def start_monitoring(self, live_view=False):
        self.live_view = live_view
        print("--------------------------------------------------")
        print("   🕵️  SHADOW COPILOT :: LINKED TO HIVE           ")
        print("--------------------------------------------------")
        print("Waiting for active session...")

        while True:
            session = self.find_latest_session()
            if session:
                if session != self.current_session_dir:
                    print(f"\n[Copilot] 📡 Locked onto session: {session.name}")
                    print(f"[Copilot] 📂 Path: {session}")
                    self.current_session_dir = session
                    self.known_files = set(os.listdir(session)) # Ignore old history
                    print("[Copilot] Streaming new events...\n")
                
                self._poll_session()
            
            time.sleep(1)

    def _poll_session(self):
        """Checks for new JSON metadata files in the current session."""
        if not self.current_session_dir or not self.current_session_dir.exists():
            return

        try:
            current_files = set(os.listdir(self.current_session_dir))
            new_files = current_files - self.known_files
            
            # Sort by name (timestamp is in filename) to show in order
            sorted_new_files = sorted(list(new_files))

            for filename in sorted_new_files:
                self.known_files.add(filename)
                
                # We only process .json files (metadata) 
                # The .pngs are referenced inside them
                if filename.endswith(".json"):
                    self._display_event(filename)

        except FileNotFoundError:
            # Session might have been deleted or moved
            pass

    def _display_event(self, json_filename):
        file_path = self.current_session_dir / json_filename
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            timestamp = data.get("timestamp", "??:??:??")
            step = data.get("step", "unknown_action")
            details = data.get("data", {})
            
            # Formatting
            print(f"[{timestamp}] ⚡ {step.upper()}")
            if details:
                print(f"   └─ Data: {details}")

            # Live View Logic
            if self.live_view:
                # Construct image filename from JSON filename or timestamp
                # Pattern from agent_tracker: TIMESTAMP_STEP.png
                # JSON is TIMESTAMP_STEP.json
                base_name = json_filename.rsplit('.', 1)[0]
                image_path = self.current_session_dir / f"{base_name}.png"
                
                if image_path.exists():
                    self._open_image(image_path)
                else:
                    # Sometimes tracker might save logic differently, verify
                    pass

        except Exception as e:
            print(f"[Copilot] Error reading event {json_filename}: {e}")

    def _open_image(self, path):
        """Opens image in default viewer (OS agnostic)."""
        import platform
        import subprocess
        
        try:
            if platform.system() == 'Darwin':       # macOS
                subprocess.call(('open', str(path)))
            elif platform.system() == 'Windows':    # Windows
                os.startfile(str(path))
            else:                                   # linux variants
                subprocess.call(('xdg-open', str(path)))
        except Exception:
            pass

if __name__ == "__main__":
    copilot = ShadowCopilot()
    
    # Simple CLI argument to enable live popup mode
    live_mode = "live" in sys.argv
    
    if live_mode:
        print("[Copilot] Live View Enabled (Popup windows for screenshots)")
    
    copilot.start_monitoring(live_view=live_mode)