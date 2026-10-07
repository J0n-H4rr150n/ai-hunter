"""
Playbook Executor - Orchestrates playbook → runbook → steps → tools execution
Bridges the declarative YAML playbooks/runbooks to imperative Python execution
"""

import asyncio
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime, timezone
from pathlib import Path

from core.playbook_manager import PlaybookManager
from core.runbook_engine import RunbookParser, RunbookExecutor, RunbookFlowManager
from core.state_manager import StateManager, StateScope
from core.tool_mapper import ToolMapper, ToolMapperError
from memory.finding_repository import FindingRepository


class PlaybookExecutionError(Exception):
    """Raised when playbook execution fails critically"""
    pass


class RunbookExecutionError(Exception):
    """Raised when a runbook step fails"""
    pass


class PlaybookExecutorContext:
    """Execution context shared across runbook executions"""
    
    def __init__(self, mission_id: int, goal: str, target_url: str, 
                 instructions: str = None):
        self.mission_id = mission_id
        self.goal = goal
        self.target_url = target_url
        self.instructions = instructions
        self.start_time = datetime.now(timezone.utc)
        self.playbook_name = None
        self.playbook = None  # Full playbook definition
        self.execution_id = None
        
        # Findings aggregation
        self.all_findings = {}  # runbook_name -> findings
        self.finding_count = 0
        
        # Execution state
        self.paused = False
        self.abort_requested = False
        self.completed_runbooks = []
        self.failed_runbooks = []
        self.current_stage = 0
        self.current_runbook = None
        self.checkpoint_enabled = True
        
    def to_checkpoint_dict(self) -> Dict[str, Any]:
        """Serialize context to dict for checkpointing"""
        return {
            'mission_id': self.mission_id,
            'goal': self.goal,
            'target_url': self.target_url,
            'instructions': self.instructions,
            'playbook_name': self.playbook_name,
            'current_stage': self.current_stage,
            'current_runbook': self.current_runbook,
            'completed_runbooks': self.completed_runbooks,
            'failed_runbooks': self.failed_runbooks,
            'all_findings': self.all_findings,
            'finding_count': self.finding_count,
            'paused': self.paused,
            'playbook': self.playbook  # Full playbook definition
        }
    
    @classmethod
    def from_checkpoint_dict(cls, data: Dict[str, Any]) -> 'PlaybookExecutorContext':
        """Restore context from checkpoint dict"""
        ctx = cls(
            mission_id=data['mission_id'],
            goal=data['goal'],
            target_url=data['target_url'],
            instructions=data.get('instructions')
        )
        ctx.playbook_name = data.get('playbook_name')
        ctx.current_stage = data.get('current_stage', 0)
        ctx.current_runbook = data.get('current_runbook')
        ctx.completed_runbooks = data.get('completed_runbooks', [])
        ctx.failed_runbooks = data.get('failed_runbooks', [])
        ctx.all_findings = data.get('all_findings', {})
        ctx.finding_count = data.get('finding_count', 0)
        ctx.paused = data.get('paused', False)
        ctx.playbook = data.get('playbook')
        return ctx


class PlaybookExecutor:
    """
    Executes playbooks by orchestrating runbooks and integrating with the autonomous agent.
    
    Responsibilities:
    - Validate playbook before execution
    - Execute runbooks in sequence order
    - Handle conditional branching based on findings
    - Manage HITL (Human-in-the-Loop) checkpoints
    - Aggregate findings across runbooks
    - Persist state for pause/resume
    - Handle errors gracefully with rollback
    """
    
    def __init__(self, autonomous_loop=None, db=None, playbook_manager=None, 
                 state_manager=None, tracker=None, repo=None, quota=None):
        """
        Args:
            autonomous_loop: AutonomousLoop instance (legacy, provides access to tools, browser, agent)
            db: Database instance for persistence
            playbook_manager: Optional PlaybookManager (for standalone use)
            state_manager: Optional StateManager (for standalone use)
            tracker: Optional AgentTracker (for standalone use)
            repo: Optional FindingRepository (for standalone use)
            quota: Optional QuotaManager (for standalone use)
        """
        # Support both legacy and new initialization patterns
        if autonomous_loop:
            # Legacy pattern: autonomous_loop provides everything
            self.loop = autonomous_loop
            self.db = db
            self.manager = PlaybookManager()
            self.state_manager = StateManager(db)
            self.finding_repo = autonomous_loop.repo
            self.tracker = getattr(autonomous_loop, 'tracker', None)
            self.quota = getattr(autonomous_loop, 'quota', None)
        else:
            # New pattern: direct component injection
            self.loop = None
            self.db = db
            self.manager = playbook_manager or PlaybookManager()
            self.state_manager = state_manager
            self.finding_repo = repo
            self.tracker = tracker
            self.quota = quota
        
        # Core components
        self.runbook_parser = RunbookParser()
        self.flow_manager = RunbookFlowManager(self.runbook_parser)
        
        # Tool mapper for action execution
        if autonomous_loop:
            self.tool_mapper = ToolMapper(
                browser=autonomous_loop.browser if hasattr(autonomous_loop, 'browser') else None,
                scanner=autonomous_loop.scanner if hasattr(autonomous_loop, 'scanner') else None,
                fuzzer=autonomous_loop.fuzzer if hasattr(autonomous_loop, 'fuzzer') else None,
                repo=autonomous_loop.repo
            )
        else:
            # Create minimal tool mapper for standalone use
            self.tool_mapper = ToolMapper(
                browser=None,
                scanner=None,
                fuzzer=None,
                repo=repo
            )
        
        # Execution context
        self.context: Optional[PlaybookExecutorContext] = None
        self.current_runbook_executor: Optional[RunbookExecutor] = None
        self.progress_callback: Optional[callable] = None
        
        # Checkpoint configuration
        self.auto_checkpoint = True  # Auto-checkpoint after each runbook
        self.checkpoint_interval = 1  # Checkpoint every N runbooks
        
    def _log(self, message: str, screenshot: dict = None):
        """Log to UI and console"""
        if self.loop and self.loop.ui_callback:
            self.loop.log_to_ui(message, screenshot)
        else:
            print(message)
    
    async def _publish_progress(self, progress_data: dict):
        """Publish progress updates via callback"""
        if self.progress_callback:
            try:
                if asyncio.iscoroutinefunction(self.progress_callback):
                    await self.progress_callback(progress_data)
                else:
                    self.progress_callback(progress_data)
            except Exception as e:
                print(f"[Playbook] Error publishing progress: {e}")
    
    async def create_checkpoint(self, checkpoint_name: str = None) -> str:
        """Create a checkpoint of current playbook state"""
        if not self.context:
            raise PlaybookExecutionError("No active context to checkpoint")
        
        # Generate checkpoint name if not provided
        if not checkpoint_name:
            checkpoint_name = f"auto_stage_{self.context.current_stage}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        
        # Serialize context
        checkpoint_data = self.context.to_checkpoint_dict()
        
        # Save to StateManager
        await self.state_manager.checkpoint(
            mission_id=self.context.mission_id,
            name=checkpoint_name,
            full_state=checkpoint_data
        )
        
        self._log(f"[Checkpoint] 💾 Saved checkpoint: {checkpoint_name}")
        
        # Publish checkpoint event
        await self._publish_progress({
            'checkpoint_created': checkpoint_name,
            'stage': self.context.current_stage,
            'runbooks_completed': len(self.context.completed_runbooks)
        })
        
        return checkpoint_name
    
    async def restore_checkpoint(self, checkpoint_name: str) -> bool:
        """Restore playbook state from checkpoint"""
        self._log(f"[Checkpoint] 🔄 Restoring checkpoint: {checkpoint_name}")
        
        # Load checkpoint data
        checkpoint_data = await self.state_manager.restore_checkpoint(
            mission_id=self.context.mission_id if self.context else 0,
            name=checkpoint_name
        )
        
        if not checkpoint_data:
            self._log(f"[Checkpoint] ❌ Checkpoint not found: {checkpoint_name}")
            return False
        
        # Restore context
        self.context = PlaybookExecutorContext.from_checkpoint_dict(checkpoint_data)
        
        self._log(f"[Checkpoint] ✅ Restored to stage {self.context.current_stage}")
        self._log(f"[Checkpoint] 📊 Completed runbooks: {len(self.context.completed_runbooks)}")
        
        # Publish restore event
        await self._publish_progress({
            'checkpoint_restored': checkpoint_name,
            'stage': self.context.current_stage,
            'runbooks_completed': len(self.context.completed_runbooks)
        })
        
        return True
    
    async def list_checkpoints(self) -> List[Dict[str, Any]]:
        """List all checkpoints for current mission"""
        if not self.context:
            return []
        
        return await self.state_manager.list_checkpoints(self.context.mission_id)
    
    def pause_execution(self):
        """Pause playbook execution at next safe point"""
        if self.context:
            self.context.paused = True
            self._log("[Playbook] ⏸️  Pause requested - will pause after current step")
    
    def resume_execution(self):
        """Resume paused playbook execution"""
        if self.context:
            self.context.paused = False
            self._log("[Playbook] ▶️  Resuming execution")
    
    def is_paused(self) -> bool:
        """Check if execution is paused"""
        return self.context.paused if self.context else False
    async def execute_playbook(self, playbook_name: str, goal: str = None, 
                              target_url: str = None, mission_id: int = None,
                              instructions: str = None,
                              context_dict: Dict[str, Any] = None,
                              progress_callback: callable = None,
                              skip_validation: bool = False) -> Dict[str, Any]:
        """
        Main entry point for playbook execution.
        
        Args:
            playbook_name: Name of playbook YAML file (without .yaml)
            goal: Mission objective (can be in context_dict)
            target_url: Target URL to test (can be in context_dict)
            mission_id: Database mission ID (optional)
            instructions: Optional user instructions (can be in context_dict)
            context_dict: Alternative way to pass all context as dict
            progress_callback: Optional async callback for progress updates
            skip_validation: Skip pre-flight validation (NOT RECOMMENDED)
        
        Returns:
            Execution summary with findings and status
        
        Raises:
            PlaybookExecutionError: If validation fails or critical error occurs
        """
        
        # Support both parameter styles
        if context_dict:
            target_url = context_dict.get("target_url", target_url)
            instructions = context_dict.get("instructions", instructions)
            goal = context_dict.get("goal", goal)
            mission_id = context_dict.get("mission_id", mission_id)
        
        # Default values
        goal = goal or "Execute playbook"
        mission_id = mission_id or 0
        
        # Store progress callback
        self.progress_callback = progress_callback
        
        # Initialize context
        self.context = PlaybookExecutorContext(mission_id, goal, target_url, instructions)
        self.context.playbook_name = playbook_name
        
        self._log(f"[Playbook] 🎯 Starting Playbook: {playbook_name}")
        self._log(f"[Playbook] 🚀 Goal: {goal}")
        self._log(f"[Playbook] 🌐 Target: {target_url}")
        
        try:
            # STEP 1: Validation
            if not skip_validation:
                self._log("[Playbook] ✔️  Validating playbook structure...")
                validation_result = self.manager.validate_playbook_preflight(playbook_name)
                
                if not validation_result.is_valid():
                    error_msg = f"Playbook validation failed:\n{validation_result.summary()}"
                    self._log(f"[Playbook] ❌ {error_msg}")
                    raise PlaybookExecutionError(error_msg)
                
                if validation_result.has_warnings():
                    for warning in validation_result.get_warnings():
                        self._log(f"[Playbook] ⚠️  {warning.message}")
            
            # STEP 2: Start playbook
            self._log("[Playbook] 📋 Loading playbook configuration...")
            playbook_info = self.manager.start_playbook(playbook_name, goal, skip_validation=True)
            
            # Load and store the full playbook definition
            playbook = self.manager.load_playbook(playbook_name)
            self.context.playbook = playbook
            self.context.playbook_name = playbook_name
            
            total_stages = playbook_info['total_stages']
            self._log(f"[Playbook] 📊 Total stages: {total_stages}")
            
            # STEP 3: Create execution record in database
            self.context.execution_id = await self._create_playbook_execution_record(
                playbook_name, playbook_info
            )
            
            # STEP 3.5: Create iteration plan for UI display
            if self.db and mission_id:
                await self._create_playbook_iteration_plan(mission_id, playbook, total_stages)
            
            # STEP 4: Execute runbooks in sequence
            self._log("[Playbook] 🔄 Beginning runbook execution sequence...")
            
            stage_num = 0
            while True:
                stage_num += 1
                
                # Check for pause/abort
                if self.context.paused:
                    self._log("[Playbook] ⏸️  Execution paused")
                    await self._update_execution_status('paused')
                    return self._build_execution_summary('paused')
                
                if self.context.abort_requested:
                    self._log("[Playbook] 🛑 Execution aborted by user")
                    await self._update_execution_status('aborted')
                    return self._build_execution_summary('aborted')
                
                # Get next runbook
                next_runbook = self.manager.get_next_runbook(
                    current_findings=self.context.all_findings
                )
                
                if not next_runbook:
                    self._log("[Playbook] ✅ All runbooks completed!")
                    break
                
                runbook_name = next_runbook['runbook']
                stage = next_runbook['stage']
                
                self._log(f"\n[Playbook] 📍 Stage {stage}/{total_stages}: {next_runbook.get('name', runbook_name)}")
                
                # HITL Checkpoint
                if next_runbook.get('hitl_checkpoint', False):
                    self._log(f"[Playbook] 🚦 HITL Checkpoint before: {runbook_name}")
                    
                    approval = await self._request_hitl_checkpoint_approval(next_runbook)
                    
                    if not approval['approved']:
                        if approval.get('action') == 'abort':
                            self._log("[Playbook] 🛑 User aborted at checkpoint")
                            self.context.abort_requested = True
                            continue
                        elif approval.get('action') == 'skip':
                            self._log(f"[Playbook] ⏭️  User skipped runbook: {runbook_name}")
                            self.manager.complete_stage(stage, {'skipped': True})
                            continue
                
                # Execute runbook
                try:
                    findings = await self._execute_runbook(runbook_name, stage)
                    
                    # Record completion
                    self.manager.complete_stage(stage, findings)
                    self.flow_manager.record_runbook_completion(runbook_name, findings)
                    self.context.completed_runbooks.append(runbook_name)
                    self.context.all_findings[runbook_name] = findings
                    self.context.current_stage = stage
                    
                    self._log(f"[Playbook] ✅ Stage {stage} complete: {runbook_name}")
                    
                    # Auto-checkpoint after runbook completion
                    if self.auto_checkpoint and stage % self.checkpoint_interval == 0:
                        checkpoint_name = await self.create_checkpoint()
                        self._log(f"[Checkpoint] 💾 Auto-saved: {checkpoint_name}")
                    
                    # Publish runbook completed
                    await self._publish_progress({
                        "runbook_completed": runbook_name,
                        "completed_runbooks": self.context.completed_runbooks,
                        "current_stage": stage + 1,
                        "total_stages": len(self.context.playbook.get('sequence', [])),
                        "findings_count": sum(len(f) for f in self.context.all_findings.values() if isinstance(f, list))
                    })
                    
                except RunbookExecutionError as e:
                    self._log(f"[Playbook] ❌ Runbook failed: {runbook_name} - {e}")
                    self.context.failed_runbooks.append({
                        'runbook': runbook_name,
                        'error': str(e)
                    })
                    
                    # Check if this runbook was required
                    if next_runbook.get('required', True):
                        raise PlaybookExecutionError(f"Required runbook failed: {runbook_name}")
                    else:
                        self._log(f"[Playbook] ⚠️  Optional runbook failed, continuing...")
            
            # STEP 5: Playbook complete
            await self._update_execution_status('completed')
            
            # Check success criteria
            is_successful = self.manager.is_playbook_complete()
            
            if is_successful:
                self._log("[Playbook] 🎉 Playbook execution SUCCESSFUL!")
            else:
                self._log("[Playbook] ⚠️  Playbook completed with some stages incomplete")
            
            # STEP 6: Final summary
            summary = self._build_execution_summary('completed')
            self._log(f"[Playbook] 📊 Total findings: {self.context.finding_count}")
            self._log(f"[Playbook] 📊 Runbooks completed: {len(self.context.completed_runbooks)}")
            
            return summary
            
        except PlaybookExecutionError as e:
            self._log(f"[Playbook] ❌ CRITICAL ERROR: {e}")
            await self._update_execution_status('failed')
            raise
        
        except Exception as e:
            self._log(f"[Playbook] ❌ UNEXPECTED ERROR: {e}")
            await self._update_execution_status('failed')
            raise PlaybookExecutionError(f"Unexpected error during playbook execution: {e}")
    
    async def _execute_runbook(self, runbook_name: str, stage: int) -> Dict[str, Any]:
        """
        Execute a single runbook and return aggregated findings.
        
        Args:
            runbook_name: Name of runbook to execute
            stage: Stage number in playbook sequence
        
        Returns:
            Dict of findings from all runbook steps
        
        Raises:
            RunbookExecutionError: If runbook execution fails
        """
        
        self._log(f"[Runbook] 🔧 Loading runbook: {runbook_name}")
        
        # Update context
        if self.context:
            self.context.current_stage = stage
            self.context.current_runbook = runbook_name
        
        # Publish runbook started
        await self._publish_progress({
            "runbook_started": runbook_name,
            "current_runbook": runbook_name,
            "current_stage": stage,
            "total_stages": len(self.context.playbook.get('sequence', [])) if self.context.playbook else 0
        })
        
        try:
            # Load runbook
            runbook = self.runbook_parser.load_runbook(runbook_name)
            
            # Create runbook executor
            self.current_runbook_executor = RunbookExecutor(runbook, self.finding_repo)
            
            # Get steps in dependency order
            ordered_steps = self.runbook_parser.get_steps_in_order(runbook)
            
            self._log(f"[Runbook] 📋 Steps to execute: {len(ordered_steps)}")
            
            # Create runbook execution record
            runbook_exec_id = await self._create_runbook_execution_record(
                runbook_name, stage
            )
            
            # Execute each step
            for i, step in enumerate(ordered_steps, 1):
                step_id = step['id']
                step_name = step['name']
                
                self._log(f"[Runbook] 📍 Step {i}/{len(ordered_steps)}: {step_name}")
                
                # Publish step progress
                await self._publish_progress({
                    "current_runbook": runbook_name,
                    "current_step": {
                        "id": step_id,
                        "name": step_name,
                        "number": i,
                        "total": len(ordered_steps)
                    },
                    "current_stage": stage,
                    "total_stages": len(self.context.playbook.get('sequence', [])) if self.context.playbook else 0
                })
                
                # Check dependencies
                depends_on = step.get('depends_on', [])
                if not all(dep in self.current_runbook_executor.completed_steps for dep in depends_on):
                    missing = [d for d in depends_on if d not in self.current_runbook_executor.completed_steps]
                    raise RunbookExecutionError(f"Step {step_id} dependencies not met: {missing}")
                
                # Execute step
                try:
                    step_findings = await self._execute_step(step, runbook)
                    
                    # Record findings
                    self.current_runbook_executor.record_step_findings(step_id, step_findings)
                    self.context.finding_count += len(step_findings)
                    
                    self._log(f"[Runbook] ✅ Step complete: {step_name}")
                    
                except Exception as e:
                    self._log(f"[Runbook] ❌ Step failed: {step_name} - {e}")
                    raise RunbookExecutionError(f"Step '{step_name}' failed: {e}")
            
            # Get all findings from runbook
            all_findings = self.current_runbook_executor.get_all_findings()
            
            # Update database
            await self._update_runbook_execution_record(runbook_exec_id, 'completed', all_findings)
            
            self._log(f"[Runbook] ✅ Runbook complete: {runbook_name}")
            
            return all_findings
            
        except Exception as e:
            if hasattr(self, 'current_runbook_executor') and self.current_runbook_executor:
                await self._update_runbook_execution_record(
                    runbook_exec_id, 'failed', 
                    {'error': str(e)}
                )
            raise RunbookExecutionError(f"Runbook '{runbook_name}' failed: {e}")
    
    async def _execute_step(self, step: dict, runbook: dict) -> Dict[str, Any]:
        """
        Execute a single runbook step using ToolMapper.
        
        Args:
            step: Step definition from runbook
            runbook: Full runbook context
        
        Returns:
            Dict of findings from this step
        """
        
        action = step.get('action')
        tool_name = step.get('tool', 'unknown')
        
        # Handle agent_guided steps without action
        if not action:
            agent_mode = step.get('agent_mode')
            if agent_mode == 'agent_guided':
                self._log(f"[Step] 🤖 Agent-guided step (requires LLM planning)")
                # This should be handled by agent_guided execution path
                return await self._execute_step_with_agent_guidance(step, runbook, {
                    'mission_id': self.context.mission_id,
                    'goal': self.context.goal,
                    'target_url': self.context.target_url,
                    'playbook_name': self.context.playbook_name,
                })
            else:
                raise ValueError(f"Step '{step.get('name')}' missing 'action' field")
        
        self._log(f"[Step] 🔨 Action: {action}, Tool: {tool_name}")
        
        # Update tool mapper with latest browser reference
        if self.loop.browser:
            self.tool_mapper.set_browser(self.loop.browser)
        
        # Build execution context
        execution_context = {
            'mission_id': self.context.mission_id,
            'goal': self.context.goal,
            'target_url': self.context.target_url,
            'playbook_name': self.context.playbook_name,
            'runbook_name': runbook['metadata']['name'],
            'step_id': step['id']
        }
        
        # Check if agent should be involved in this step
        agent_mode = step.get('agent_mode', 'tool_only')  # 'tool_only', 'agent_guided', 'agent_free'
        
        if agent_mode == 'agent_guided' and hasattr(self.loop, 'agent') and self.loop.agent:
            # Let agent plan the step execution with runbook guidance
            findings = await self._execute_step_with_agent_guidance(step, runbook, execution_context)
        elif agent_mode == 'agent_free' and hasattr(self.loop, 'agent') and self.loop.agent:
            # Let agent execute freely (minimal runbook guidance)
            findings = await self._execute_step_with_agent_free(step, runbook, execution_context)
        else:
            # Pure tool execution (default)
            findings = await self._execute_step_with_tools(step, execution_context)
        
        return findings
    
    async def _execute_step_with_tools(self, step: dict, execution_context: dict) -> Dict[str, Any]:
        """Execute step using ToolMapper only (no agent involvement)"""
        
        action = step.get('action')
        
        # Handle agent_guided steps without explicit action
        if not action:
            agent_mode = step.get('agent_mode')
            if agent_mode == 'agent_guided':
                # This step requires LLM guidance, skip tool execution
                self._log(f"[Step] 🤖 Agent-guided step (no direct tool action)")
                return {
                    '_step_id': step['id'],
                    '_agent_mode': 'agent_guided',
                    '_note': 'Step requires LLM guidance for execution'
                }
            else:
                raise ValueError(f"Step '{step.get('name')}' missing 'action' field")
        
        try:
            # Execute action using ToolMapper in thread pool (for Playwright sync API compatibility)
            findings = await asyncio.to_thread(
                self.tool_mapper.execute_action,
                action,
                step,
                execution_context
            )
            
            # Validate findings match expected schema (optional)
            expected_findings = step.get('findings_to_log', [])
            if expected_findings:
                self._log(f"[Step] 📊 Expected {len(expected_findings)} findings, got {len(findings)} actual")
            
            return findings
            
        except ToolMapperError as e:
            self._log(f"[Step] ❌ Tool mapping error: {e}")
            # Raise exception to stop execution
            raise RunbookExecutionError(f"Step '{step.get('name')}' failed: {e}")
        
        except Exception as e:
            self._log(f"[Step] ❌ Unexpected error: {e}")
            raise RunbookExecutionError(f"Step '{step.get('name')}' failed: {e}")
    
    async def _execute_step_with_agent_guidance(self, step: dict, runbook: dict, 
                                               execution_context: dict) -> Dict[str, Any]:
        """
        Execute step with LLM-generated iteration plan.
        
        This generates a custom plan for accomplishing the step objective,
        stores it as an iteration in the database, publishes to UI, then executes.
        """
        
        step_name = step['name']
        step_description = step.get('description', '')
        action = step.get('action')  # May not exist for agent_guided steps
        
        self._log(f"[Step] 🤖 Agent-guided execution for: {step_name}")
        
        # For now, agent-guided steps without explicit actions return placeholder
        # TODO: Implement full LLM planning integration
        if not action:
            self._log(f"[Step] 📝 Agent will analyze: {step_description}")
            return {
                '_step_id': step.get('id'),
                '_step_name': step_name,
                '_agent_mode': 'agent_guided',
                '_description': step_description,
                '_note': 'Agent-guided step completed (LLM planning integration pending)'
            }
        
        self._log(f"[Step] 🤖 Generating plan for: {step_name}")
        
        # Fallback if no browser or database
        if not self.loop.browser or not self.db:
            self._log(f"[Step] ⚠️  Missing browser or database, falling back to tools")
            return await self._execute_step_with_tools(step, execution_context)
        
        try:
            # STEP 1: Get previous iterations for context
            previous_iterations = await self.db.get_mission_iterations(self.context.mission_id)
            iteration_number = len(previous_iterations) + 1
            
            self._log(f"[Step] 📚 Previous iterations: {len(previous_iterations)}")
            
            # STEP 2: Get current page state
            triad = None
            try:
                triad = self.loop.browser.get_snapshot_triad()
            except:
                pass  # Continue without visual context if unavailable
            
            # STEP 3: Build context for LLM planner
            planning_context = {
                'mission_goal': execution_context['goal'],
                'target_url': execution_context['target_url'],
                'step_objective': f"{step_name}: {step_description}",
                'previous_findings': [
                    {
                        'iteration': iter['iteration_number'],
                        'findings': iter.get('findings_summary', 'No summary')
                    }
                    for iter in previous_iterations
                ],
                'available_tools': [
                    'navigate', 'screenshot', 'view_source', 'inspect_dom',
                    'parse_url', 'monitor_network', 'check_forms'
                ]
            }
            
            # STEP 4: Generate plan using TacticalPlanner
            from core.tactical_planner import TacticalPlanner
            planner = TacticalPlanner()
            
            # Build step-specific goal
            step_goal = f"{step_name}: {step_description}. Target: {execution_context['target_url']}"
            
            # Generate plan (may need to adapt TacticalPlanner to accept step context)
            plan = planner.generate_plan(
                goal=step_goal,
                triad=triad,
                tech_report=planning_context  # Pass context as tech_report
            )
            
            self._log(f"[Step] ✨ Generated plan with {len(plan.get('steps', []))} steps")
            
            # STEP 5: Create iteration in database
            iteration_id = await self.db.create_iteration(
                mission_id=self.context.mission_id,
                iteration_number=iteration_number,
                plan=plan
            )
            
            await self.db.update_iteration_status(iteration_id, "in_progress")
            
            self._log(f"[Step] 💾 Created iteration {iteration_number} (ID: {iteration_id})")
            
            # STEP 6: Publish plan to UI
            await self._publish_progress({
                "type": "iteration_plan",
                "iteration_number": iteration_number,
                "plan": {
                    "rationale": plan.get('rationale', step_description),
                    "steps": plan.get('steps', []),
                    "budgets": plan.get('budgets', {})
                }
            })
            
            self._log(f"[Step] 📤 Published plan to UI")
            
            # STEP 7: Execute the generated plan
            findings = await self._execute_generated_plan(plan, step, execution_context)
            
            # STEP 8: Update iteration with results
            findings_summary = f"Completed {step_name}. Found: {len(findings)} findings"
            await self.db.update_iteration_status(
                iteration_id,
                "completed",
                findings_summary
            )
            
            self._log(f"[Step] ✅ Iteration {iteration_number} complete")
            
            return findings
            
        except Exception as e:
            self._log(f"[Step] ⚠️  LLM planning failed: {e}, falling back to tools")
            import traceback
            traceback.print_exc()
            return await self._execute_step_with_tools(step, execution_context)
    
    async def _execute_generated_plan(self, plan: dict, original_step: dict, 
                                     execution_context: dict) -> Dict[str, Any]:
        """
        Execute a plan generated by the LLM.
        
        Args:
            plan: Generated plan with steps/budgets
            original_step: Original runbook step
            execution_context: Execution context
            
        Returns:
            Aggregated findings from plan execution
        """
        
        all_findings = {}
        plan_steps = plan.get('steps', [])
        
        self._log(f"[Plan] Executing {len(plan_steps)} plan steps...")
        
        for i, plan_step in enumerate(plan_steps, 1):
            # Convert plan step to tool action
            if isinstance(plan_step, str):
                # Simple string step - try to infer action
                action_text = plan_step.lower()
                if 'navigate' in action_text:
                    action = 'navigate'
                    tool = 'som_browser'
                elif 'screenshot' in action_text or 'capture' in action_text:
                    action = 'capture_screenshot'
                    tool = 'som_browser'
                elif 'source' in action_text or 'html' in action_text:
                    action = 'view_source'
                    tool = 'som_browser'
                else:
                    # Default to the original step's action
                    action = original_step.get('action', 'unknown')
                    tool = original_step.get('tool', 'unknown')
            elif isinstance(plan_step, dict):
                # Structured step
                action = plan_step.get('action', original_step.get('action'))
                tool = plan_step.get('tool', original_step.get('tool'))
            else:
                continue
            
            self._log(f"[Plan] Step {i}/{len(plan_steps)}: {action}")
            
            # Create temporary step dict for execution
            temp_step = {
                'id': f"{original_step['id']}_plan_{i}",
                'name': f"Plan step {i}",
                'action': action,
                'tool': tool,
                'inputs': plan_step.get('inputs', {}) if isinstance(plan_step, dict) else {}
            }
            
            try:
                step_findings = await self._execute_step_with_tools(temp_step, execution_context)
                all_findings[f"step_{i}"] = step_findings
            except Exception as e:
                self._log(f"[Plan] ⚠️  Step {i} failed: {e}")
                all_findings[f"step_{i}_error"] = str(e)
        
        return all_findings

    
    async def _execute_step_with_agent_free(self, step: dict, runbook: dict,
                                            execution_context: dict) -> Dict[str, Any]:
        """
        Execute step with agent in free-form mode.
        
        Agent receives minimal guidance and operates autonomously to achieve
        the step's high-level objective.
        """
        
        self._log(f"[Step] 🤖 Agent free-form execution for: {step['name']}")
        
        # This would integrate with the autonomous loop's main execution
        # The agent would execute autonomously until the step objective is met
        
        # For now, return placeholder
        return {
            'agent_free_mode': True,
            'step_objective': step['description'],
            'note': 'Agent free-form execution not yet fully integrated'
        }
    
    async def _request_hitl_checkpoint_approval(self, runbook_info: dict) -> Dict[str, Any]:
        """
        Request human approval at a HITL checkpoint.
        
        Args:
            runbook_info: Runbook information from playbook sequence
        
        Returns:
            Dict with approval status and optional action
        """
        
        # TODO: Phase 5 - Implement actual HITL UI integration
        # For now, auto-approve if no callback is set
        
        if not self.loop.tool_approval_callback:
            self._log("[HITL] No approval callback set, auto-approving checkpoint")
            return {'approved': True, 'action': 'continue'}
        
        # Build approval request
        approval_request = {
            'type': 'hitl_checkpoint',
            'runbook': runbook_info['runbook'],
            'stage': runbook_info['stage'],
            'name': runbook_info.get('name', ''),
            'description': runbook_info.get('description', ''),
            'current_findings': self.context.all_findings,
            'completed_runbooks': self.context.completed_runbooks
        }
        
        # Request approval (blocks until response)
        approval = self.loop.tool_approval_callback(
            'hitl_checkpoint', 
            approval_request,
            {'mission_id': self.context.mission_id}
        )
        
        return approval
    
    async def _create_playbook_execution_record(self, playbook_name: str, 
                                               playbook_info: dict) -> int:
        """Create database record for playbook execution"""
        
        # TODO: Phase 1, Task 1.3 - Implement database schema
        # For now, return placeholder ID
        return 1
    
    async def _create_playbook_iteration_plan(self, mission_id: int, playbook: dict, total_stages: int):
        """Create an iteration plan from playbook sequence for UI display"""
        
        if not self.db:
            return
        
        try:
            # Build plan from playbook sequence
            sequence = playbook.get('sequence', [])
            
            plan = {
                'goal': playbook.get('metadata', {}).get('description', 'Execute playbook'),
                'target_url': self.context.target_url,
                'instructions': self.context.instructions,
                'total_stages': total_stages,
                'stages': []
            }
            
            # Convert each runbook in sequence to a stage
            for item in sequence:
                stage = {
                    'stage': item.get('stage'),
                    'name': item.get('name', item['runbook']),
                    'runbook': item['runbook'],
                    'description': item.get('description', ''),
                    'required': item.get('required', True),
                    'hitl_checkpoint': item.get('hitl_checkpoint', False)
                }
                plan['stages'].append(stage)
            
            # Create iteration in database
            iteration_id = await self.db.create_iteration(
                mission_id=mission_id,
                iteration_number=1,
                plan=plan,
                status='in_progress'
            )
            
            self._log(f"[Playbook] 📋 Created iteration plan (ID: {iteration_id})")
            
            return iteration_id
            
        except Exception as e:
            self._log(f"[Playbook] ⚠️  Failed to create iteration plan: {e}")
            # Don't fail the mission if plan creation fails
            return None
    
    async def _create_runbook_execution_record(self, runbook_name: str, stage: int) -> int:
        """Create database record for runbook execution"""
        
        # TODO: Phase 1, Task 1.3 - Implement database schema
        return 1
    
    async def _update_execution_status(self, status: str):
        """Update playbook execution status in database"""
        
        # TODO: Phase 1, Task 1.3 - Implement database updates
        pass
    
    async def _update_runbook_execution_record(self, runbook_exec_id: int, 
                                              status: str, findings: Dict):
        """Update runbook execution record"""
        
        # TODO: Phase 1, Task 1.3 - Implement database updates
        pass
    
    def _build_execution_summary(self, status: str) -> Dict[str, Any]:
        """Build final execution summary"""
        
        duration = (datetime.now(timezone.utc) - self.context.start_time).total_seconds()
        
        return {
            'status': status,
            'playbook_name': self.context.playbook_name,
            'mission_id': self.context.mission_id,
            'goal': self.context.goal,
            'target_url': self.context.target_url,
            'execution_id': self.context.execution_id,
            'duration_seconds': duration,
            'completed_runbooks': self.context.completed_runbooks,
            'failed_runbooks': self.context.failed_runbooks,
            'total_findings': self.context.finding_count,
            'all_findings': self.context.all_findings,
            'is_success': len(self.context.failed_runbooks) == 0 and status == 'completed'
        }
    
    # Pause/Resume functionality (Phase 6)
    
    async def pause_execution(self):
        """Pause playbook execution at next checkpoint"""
        self.context.paused = True
        self._log("[Playbook] ⏸️  Pause requested")
    
    async def resume_execution(self):
        """Resume paused execution"""
        if not self.context or not self.context.paused:
            raise PlaybookExecutionError("No paused execution to resume")
        
        self.context.paused = False
        self._log("[Playbook] ▶️  Resuming execution")
        
        # TODO: Phase 6 - Implement checkpoint restoration
    
    def abort_execution(self):
        """Request abort at next checkpoint"""
        self.context.abort_requested = True
        self._log("[Playbook] 🛑 Abort requested")
