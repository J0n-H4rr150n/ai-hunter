import json
import os
from datetime import datetime, date
from pathlib import Path
from config.config import Config
from config.safety import HARD_CAPS

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

    # Used for an action the planner gave no budget for.
    DEFAULT_PER_ACTION_LIMIT = 25

    def __init__(self, agent_id="global"):
        self.agent_id = agent_id
        
        # Persistent storage for quota state
        # Storing in hive_bucket/state to persist across sessions
        self.state_dir = Config.HIVE_BUCKET_ROOT / "state"
        self.state_file = self.state_dir / f"quota_{self.agent_id}.json"
        
        self._ensure_storage()
        self.usage = self._load_state()
        self.custom_limits = {}

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
        limit = self._limit_for(metric)
        current_usage = self.usage.get(metric, 0)

        if current_usage >= limit:
            print(f"[Quota] 🛑 LIMIT REACHED: {metric} ({current_usage}/{limit})")
            return False

        return True

    def _limit_for(self, metric: str) -> float:
        """
        Resolve the ceiling for a metric.

        Order matters: a budget approved with the plan beats a global default.
        set_limit() stored those in custom_limits, but check_limit never read it,
        so the per-plan budgets were accepted and then ignored entirely.

        An unknown metric previously resolved to None and the comparison raised
        TypeError, which took down every caller that asked about anything outside
        the three built-in metrics.
        """
        custom = getattr(self, "custom_limits", {})
        if metric in custom:
            return custom[metric]

        limit_key = f"{metric}_daily"
        configured = getattr(Config, limit_key.upper(), None)
        if configured is not None:
            return configured
        if limit_key in self.DEFAULT_LIMITS:
            return self.DEFAULT_LIMITS[limit_key]

        # Per-action budgets the planner may not have specified. Fall back to the
        # engine's hard cap rather than refusing outright or crashing.
        return HARD_CAPS.get(metric, self.DEFAULT_PER_ACTION_LIMIT)

    def tally(self, metric: str, amount: float = 1.0):
        """
        Records usage of a resource.
        
        Args:
            metric (str): The resource being used (e.g., 'actions').
            amount (float): The amount to add.
        """
        # Reload state in case other processes updated it (simple concurrency)
        self.usage = self._load_state()
        self.custom_limits = {}
        
        if metric not in self.usage:
            self.usage[metric] = 0
            
        self.usage[metric] += amount
        self._save_state()
        
        if Config.DEBUG:
            # Optional: Verbose logging
            # print(f"[Quota] {metric} +{amount} = {self.usage[metric]}")
            pass

    def set_limit(self, tool_name: str, limit: int):
        """
        Override the default limit for a specific tool/metric.
        
        Args:
            tool_name (str): The tool or metric name (e.g., 'actions', 'llm_tokens')
            limit (int): The new limit value
        """
        self.custom_limits[tool_name] = limit
        
        if Config.DEBUG:
            print(f"[Quota] Set custom limit for {tool_name}: {limit}")

    def get_status(self):
        """Returns a summary of current usage."""
        return self.usage