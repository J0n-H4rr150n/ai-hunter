import sys
import os
import platform
import subprocess
import json
from datetime import datetime
from pathlib import Path
from config.config import Config

class HumanInterface:
    """
    Manages interaction between the autonomous agent and the human operator.
    Handles user prompts, displaying 'shadow' context (screenshots), 
    and logging interactions to the hive bucket.
    """

    def __init__(self, agent_tracker):
        """
        Initialize with an AgentTracker instance to access session paths.
        """
        self.tracker = agent_tracker
        self.session_path = Path(self.tracker.get_session_path())

    def ask(self, question: str, shadow_path: str = None) -> str:
        """
        Prompts the human for input, optionally displaying a context image.
        
        Args:
            question (str): The prompt for the user.
            shadow_path (str): Path to a screenshot to show the user.
            
        Returns:
            str: The human's response.
        """
        timestamp = datetime.now().strftime("%H-%M-%S-%f")[:-3]
        
        print(f"\n[🤖 Agent]: {question}")
        
        if shadow_path:
            print(f"[🖼️ Displaying Context]: {shadow_path}")
            self._open_file(shadow_path)
            
        response = input(f"[👤 Human]: ").strip()
        
        # Log the interaction
        self._log_interaction(timestamp, question, response, shadow_path)
        
        return response

    def notify(self, message: str):
        """
        Send a notification to the human without waiting for input.
        """
        print(f"[🔔 Notification]: {message}")

    def _open_file(self, filepath):
        """
        Opens a file using the default system application.
        This allows the human to instantly see what the agent sees.
        """
        filepath = str(filepath)
        try:
            if platform.system() == 'Darwin':       # macOS
                subprocess.call(('open', filepath))
            elif platform.system() == 'Windows':    # Windows
                os.startfile(filepath)
            else:                                   # linux variants
                subprocess.call(('xdg-open', filepath))
        except Exception as e:
            print(f"[⚠️ Error]: Could not open context file: {e}")

    def _log_interaction(self, timestamp, question, response, context_path):
        """
        Saves the dialogue to the hive bucket so the agent can 'remember' 
        or train on human feedback later.
        """
        log_filename = f"{timestamp}_interaction.json"
        log_filepath = self.session_path / log_filename
        
        entry = {
            "timestamp": timestamp,
            "type": "human_interaction",
            "agent_id": self.tracker.agent_id,
            "question": question,
            "response": response,
            "context_image": str(context_path) if context_path else None
        }
        
        try:
            with open(log_filepath, 'w', encoding='utf-8') as f:
                json.dump(entry, f, indent=2)
        except Exception as e:
            print(f"[⚠️ Error]: Failed to log interaction: {e}")