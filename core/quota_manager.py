import json
import os
from datetime import datetime, date
from pathlib import Path
from config.config import Config

class QuotaManager:
    """
    Manages usage limits and budgets for the autonomous agent.
    Tracks API tokens, action counts, and spending to ensure the 
    agent stays within defined boundaries.
    """
    
    # Default limits if not specified in config
    DEFAULT_LIMITS = {
        "llm_tokens_daily": 100000,
        "actions_daily": 500,
        "spending_daily_usd": 5.00
    }

    def __init__(self, agent_id="global"):
        self.agent_id = agent_id
        
        # Persistent storage for quota state
        # Storing in hive_bucket/state to persist across sessions
        self.state_dir = Config.HIVE_BUCKET_ROOT / "state"
        self.state_file = self.state_dir / f"quota_{self.agent_id}.json"
        
        self._ensure_storage()
        self.usage = self._load_state()

    def _ensure_storage(self):
        """Ensures the state directory exists."""
        if not os.path.exists(self.state_dir):
            os.makedirs(self.state_dir, exist_ok=True)

    def _load_state(self):
        """Loads usage data, resetting if the day has changed."""
        today_str = str(date.today())
        
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                
                # Check if we need to reset for a new day
                if data.get("date") != today_str:
                    return self._reset_usage(today_str)
                
                return data
            except Exception as e:
                print(f"[Quota] Error loading state, resetting: {e}")
                return self._reset_usage(today_str)
        else:
            return self._reset_usage(today_str)

    def _reset_usage(self, date_str):
        """Creates a fresh usage record for the new day."""
        return {
            "date": date_str,
            "llm_tokens": 0,
            "actions": 0,
            "spending_usd": 0.0
        }

    def _save_state(self):
        """Persists current usage to the hive bucket."""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.usage, f, indent=2)
        except Exception as e:
            print(f"[Quota] Failed to save state: {e}")

    def check_limit(self, metric: str) -> bool:
        """
        Checks if a specific metric is within bounds.
        
        Args:
            metric (str): 'llm_tokens', 'actions', or 'spending_usd'
        
        Returns:
            bool: True if proceed is allowed, False if limit exceeded.
        """
        # Map metric to config limit key
        limit_key = f"{metric}_daily"
        limit = getattr(Config, limit_key.upper(), self.DEFAULT_LIMITS.get(limit_key))
        
        current_usage = self.usage.get(metric, 0)
        
        if current_usage >= limit:
            print(f"[Quota] 🛑 LIMIT REACHED: {metric} ({current_usage}/{limit})")
            return False
        
        return True

    def tally(self, metric: str, amount: float = 1.0):
        """
        Records usage of a resource.
        
        Args:
            metric (str): The resource being used (e.g., 'actions').
            amount (float): The amount to add.
        """
        # Reload state in case other processes updated it (simple concurrency)
        self.usage = self._load_state()
        
        if metric not in self.usage:
            self.usage[metric] = 0
            
        self.usage[metric] += amount
        self._save_state()
        
        if Config.DEBUG:
            # Optional: Verbose logging
            # print(f"[Quota] {metric} +{amount} = {self.usage[metric]}")
            pass

    def get_status(self):
        """Returns a summary of current usage."""
        return self.usage