import json
import os
import uuid
from typing import List, Dict, Optional
from config.config import Config

class Planner:
    """
    Manages the high-level mission and task queue using the Hive Bucket.
    This allows the agent to maintain state (Todo/Doing/Done) persistently.
    """

    def __init__(self, agent_id="autonomous_01"):
        self.state_dir = Config.HIVE_BUCKET_ROOT / "state"
        self.mission_file = self.state_dir / "mission.json"
        self._ensure_storage()

    def _ensure_storage(self):
        if not os.path.exists(self.state_dir):
            os.makedirs(self.state_dir, exist_ok=True)

    def set_mission(self, goal: str, target: str, instructions: str = None):
        """
        Initializes a new mission with a default heuristic plan.
        
        Args:
            goal: High-level objective (e.g., "Audit for vulnerabilities")
            target: Target URL
            instructions: Optional natural language instructions from user
                         (e.g., "Focus on ID parameters, don't create accounts")
        """
        mission_state = {
            "mission_id": str(uuid.uuid4())[:8],
            "goal": goal,
            "target": target,
            "instructions": instructions or "No specific instructions provided.",
            "status": "active",
            "tasks": [
                # 1. Reconnaissance
                {"id": "t1", "type": "scan", "target": target, "status": "pending", "description": "Identify technology stack"},
                
                # 2. Discovery (Fuzzing)
                {"id": "t2", "type": "fuzz", "target": target, "status": "pending", "description": "Fuzz URL parameters for errors"},
                
                # 3. Analysis (Verification)
                # Note: A real agent would add this dynamically if fuzzer found something.
                # We add it here as a placeholder for the logic loop.
                {"id": "t3", "type": "analyze", "target": "findings", "status": "pending", "description": "Review findings for critical vulnerabilities"}
            ],
            "current_task_id": None
        }
        self._save_mission(mission_state)
        return mission_state

    def get_mission(self) -> Optional[Dict]:
        if not os.path.exists(self.mission_file):
            return None
        try:
            with open(self.mission_file, 'r') as f:
                return json.load(f)
        except Exception:
            return None

    def get_next_task(self) -> Optional[Dict]:
        """Retrieves the next pending task."""
        mission = self.get_mission()
        if not mission or mission['status'] != 'active':
            return None

        for task in mission['tasks']:
            if task['status'] == 'pending':
                return task
        
        # If no tasks pending, mark mission complete
        mission['status'] = 'completed'
        self._save_mission(mission)
        return None

    def start_task(self, task_id: str):
        """Marks a task as in-progress."""
        self._update_task_status(task_id, "in_progress")

    def complete_task(self, task_id: str, result_summary: str = ""):
        """Marks a task as done and optionally adds a result note."""
        self._update_task_status(task_id, "completed", result_summary)

    def fail_task(self, task_id: str, error: str):
        """Marks a task as failed."""
        self._update_task_status(task_id, "failed", error)

    def add_task(self, task_type: str, target: str, description: str):
        """
        Dynamically adds a new task to the plan.
        Useful when the agent discovers a new page or API endpoint.
        """
        mission = self.get_mission()
        if not mission: 
            return

        new_task = {
            "id": f"t{len(mission['tasks']) + 1}",
            "type": task_type,
            "target": target,
            "status": "pending",
            "description": description
        }
        mission['tasks'].append(new_task)
        self._save_mission(mission)
        print(f"[Planner] 🧠 Dynamically added task: {description}")

    def _update_task_status(self, task_id, status, output=None):
        mission = self.get_mission()
        if not mission: return

        for task in mission['tasks']:
            if task['id'] == task_id:
                task['status'] = status
                if output:
                    task['output'] = output
                if status == "in_progress":
                    mission['current_task_id'] = task_id
                break
        
        self._save_mission(mission)

    def _save_mission(self, data):
        with open(self.mission_file, 'w') as f:
            json.dump(data, f, indent=2)