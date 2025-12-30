"""
Workflow state management for human-in-the-loop agent execution.
Simple interrupt-based workflow without LangGraph/LangChain dependencies.
"""

from enum import Enum
from typing import Optional, Dict, Any

class WorkflowState(Enum):
    """States in the agent workflow"""
    INIT = "init"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ABORTED = "aborted"

class MissionWorkflow:
    """
    Simple state machine for managing agent missions with human approval.
    Implements the 'interrupt' concept without external dependencies.
    """
    
    def __init__(self, goal: str, target: str, instructions: Optional[str] = None):
        self.goal = goal
        self.target = target
        self.instructions = instructions
        self.state = WorkflowState.INIT
        self.plan: Optional[Dict[str, Any]] = None
        self.human_approved = False
    
    def set_plan(self, plan: Dict[str, Any]):
        """Set the generated plan and move to approval state"""
        self.plan = plan
        self.state = WorkflowState.AWAITING_APPROVAL
    
    def approve(self, edited_plan: Optional[Dict[str, Any]] = None):
        """Approve the plan (optionally with edits) and move to execution"""
        if edited_plan:
            self.plan = edited_plan
        self.human_approved = True
        self.state = WorkflowState.EXECUTING
    
    def reject(self):
        """Reject the plan and abort mission"""
        self.human_approved = False
        self.state = WorkflowState.ABORTED
    
    def complete(self):
        """Mark mission as completed"""
        self.state = WorkflowState.COMPLETED
    
    def can_execute(self) -> bool:
        """Check if workflow can proceed to execution"""
        return (
            self.state == WorkflowState.EXECUTING and 
            self.human_approved and 
            self.plan is not None
        )
    
    def is_finished(self) -> bool:
        """Check if workflow has finished (completed or aborted)"""
        return self.state in [WorkflowState.COMPLETED, WorkflowState.ABORTED]
