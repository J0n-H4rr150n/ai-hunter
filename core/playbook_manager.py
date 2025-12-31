"""
Playbook Manager
Orchestrates sequences of runbooks for specific testing objectives
"""

import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any
from core.runbook_engine import RunbookParser, RunbookExecutor, RunbookFlowManager
from core.validation import PlaybookValidator, RunbookValidator, ValidationResult


class PlaybookManager:
    """Manage playbook loading, validation, and execution orchestration"""
    
    def __init__(self, playbooks_dir: str = "playbooks", runbooks_dir: str = "runbooks"):
        self.playbooks_dir = Path(playbooks_dir)
        self.runbooks_dir = Path(runbooks_dir)
        self.loaded_playbooks = {}
        
        # Initialize runbook infrastructure
        self.runbook_parser = RunbookParser(runbooks_dir)
        self.flow_manager = RunbookFlowManager(self.runbook_parser)
        
        # Initialize validators
        self.playbook_validator = PlaybookValidator(playbooks_dir, runbooks_dir)
        self.runbook_validator = RunbookValidator(runbooks_dir)
        
        # Track playbook execution state
        self.current_playbook = None
        self.current_stage = 0
        self.completed_stages = []
        self.playbook_findings = {}  # stage -> findings
    
    def get_available_playbooks(self) -> List[Dict[str, Any]]:
        """Get list of all available playbooks with metadata"""
        playbooks = []
        
        for yaml_file in self.playbooks_dir.glob("*.yaml"):
            try:
                with open(yaml_file, 'r', encoding='utf-8') as f:
                    playbook = yaml.safe_load(f)
                
                # Validate before adding to list
                try:
                    self._validate_playbook(playbook)
                except ValueError as ve:
                    error_msg = f"Invalid playbook {yaml_file.stem}: {ve}"
                    logger.error(f"[PlaybookManager] ❌ {error_msg}")
                    raise ValueError(error_msg) from ve
                
                metadata = playbook.get('metadata', {})
                
                playbooks.append({
                    'id': yaml_file.stem,
                    'name': metadata.get('name', yaml_file.stem),
                    'description': metadata.get('description', ''),
                    'category': metadata.get('category', 'general'),
                    'difficulty': metadata.get('difficulty', 'unknown'),
                    'duration': metadata.get('estimated_duration', 'unknown'),
                    'tags': metadata.get('tags', [])
                })
            except Exception as e:
                error_msg = f"Could not load playbook {yaml_file.stem}: {e}"
                logger.error(f"[PlaybookManager] ❌ {error_msg}")
                raise ValueError(error_msg) from e  # ABORT on playbook errors
        
        # Sort by category then name
        playbooks.sort(key=lambda x: (x['category'], x['name']))
        return playbooks
    
    def load_playbook(self, playbook_name: str) -> Dict[str, Any]:
        """Load a playbook from YAML file"""
        playbook_path = self.playbooks_dir / f"{playbook_name}.yaml"
        
        if not playbook_path.exists():
            raise FileNotFoundError(f"Playbook not found: {playbook_path}")
        
        with open(playbook_path, 'r') as f:
            playbook = yaml.safe_load(f)
        
        # Validate playbook structure
        self._validate_playbook(playbook)
        
        # Cache it
        self.loaded_playbooks[playbook_name] = playbook
        
        return playbook
    
    def _validate_playbook(self, playbook: dict):
        """Validate playbook has required fields"""
        required_fields = ['metadata', 'sequence']
        
        for field in required_fields:
            if field not in playbook:
                raise ValueError(f"Playbook missing required field: {field}")
        
        # Validate metadata
        metadata = playbook['metadata']
        if 'name' not in metadata:
            raise ValueError("Playbook metadata missing 'name'")
        
        # Validate sequence
        sequence = playbook['sequence']
        if not isinstance(sequence, list) or len(sequence) == 0:
            raise ValueError("Playbook must have at least one runbook in sequence")
        
        # Validate each sequence item
        for item in sequence:
            if 'runbook' not in item or 'stage' not in item:
                raise ValueError("Sequence item missing 'runbook' or 'stage'")
            
            # Verify runbook exists
            runbook_name = item['runbook']
            try:
                self.runbook_parser.load_runbook(runbook_name)
            except FileNotFoundError:
                raise ValueError(f"Runbook '{runbook_name}' referenced in playbook but not found")
    
    def get_runbook_sequence(self, playbook_name: str) -> List[Dict[str, Any]]:
        """
        Get the ordered sequence of runbooks for a playbook
        Returns list of dicts with runbook details
        """
        playbook = self.load_playbook(playbook_name)
        sequence = playbook['sequence']
        
        # Sort by stage
        sequence.sort(key=lambda x: x['stage'])
        
        return sequence
    
    def validate_playbook_preflight(self, playbook_name: str) -> ValidationResult:
        """
        Perform comprehensive pre-flight validation before execution
        Returns: ValidationResult with any errors/warnings
        """
        return self.playbook_validator.validate_playbook(playbook_name)
    
    def validate_runbook(self, runbook_name: str) -> ValidationResult:
        """
        Validate a single runbook
        Returns: ValidationResult with any errors/warnings
        """
        return self.runbook_validator.validate_runbook(runbook_name)
    
    def start_playbook(self, playbook_name: str, mission_goal: str, skip_validation: bool = False) -> Dict[str, Any]:
        """
        Initialize a playbook for execution
        
        Args:
            playbook_name: Name of playbook to start
            mission_goal: User's mission objective
            skip_validation: Set to True to skip pre-flight validation (NOT RECOMMENDED)
        
        Returns: {playbook_name, first_runbook, total_stages, configuration}
        Raises: ValueError if validation fails (unless skip_validation=True)
        """
        # PRE-FLIGHT VALIDATION
        if not skip_validation:
            validation = self.validate_playbook_preflight(playbook_name)
            
            if not validation.is_valid():
                # Validation failed - raise error with details
                error_details = "\n".join(str(e) for e in validation.get_errors())
                raise ValueError(
                    f"Playbook '{playbook_name}' failed validation:\n{validation.summary()}\n\n{error_details}"
                )
            
            if validation.has_warnings():
                # Log warnings but proceed
                print(f"⚠️  Playbook '{playbook_name}' has warnings:")
                for warning in validation.get_warnings():
                    print(f"  {warning}")
        
        playbook = self.load_playbook(playbook_name)
        
        self.current_playbook = playbook_name
        self.current_stage = 0
        self.completed_stages = []
        self.playbook_findings = {}
        
        sequence = self.get_runbook_sequence(playbook_name)
        first_runbook = sequence[0] if sequence else None
        
        return {
            'playbook_name': playbook_name,
            'playbook_title': playbook['metadata']['name'],
            'first_runbook': first_runbook['runbook'] if first_runbook else None,
            'first_stage': first_runbook['stage'] if first_runbook else None,
            'total_stages': len(sequence),
            'configuration': playbook.get('configuration', {}),
            'mission_goal': mission_goal
        }
    
    def get_next_runbook(self, current_findings: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """
        Get the next runbook to execute based on playbook sequence
        Handles conditional branching based on findings
        Returns: {runbook, stage, hitl_checkpoint, description} or None if complete
        """
        if not self.current_playbook:
            raise ValueError("No active playbook. Call start_playbook() first")
        
        playbook = self.loaded_playbooks[self.current_playbook]
        sequence = self.get_runbook_sequence(self.current_playbook)
        
        # Record current stage findings if provided
        if current_findings and self.current_stage > 0:
            self.playbook_findings[self.current_stage] = current_findings
        
        # Check for conditional insertions based on findings
        if current_findings:
            inserted_runbook = self._evaluate_conditional_steps(playbook, current_findings)
            if inserted_runbook:
                return inserted_runbook
        
        # Get next stage in sequence
        for item in sequence:
            stage = item['stage']
            if stage > self.current_stage:
                self.current_stage = stage
                return {
                    'runbook': item['runbook'],
                    'stage': stage,
                    'name': item.get('name', ''),
                    'description': item.get('description', ''),
                    'hitl_checkpoint': item.get('hitl_checkpoint', False),
                    'required': item.get('required', True)
                }
        
        # No more runbooks - playbook complete
        return None
    
    def _evaluate_conditional_steps(self, playbook: dict, findings: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Evaluate conditional_steps and insert runbooks if conditions met
        Returns inserted runbook dict or None
        """
        conditional_steps = playbook.get('conditional_steps', [])
        
        for cond_step in conditional_steps:
            condition = cond_step.get('condition', {})
            cond_type = condition.get('type', '')
            
            if cond_type == 'finding_match':
                pattern = condition.get('pattern', '')
                # Check if pattern matches in findings
                if self._pattern_matches_findings(pattern, findings):
                    then_action = cond_step.get('then', {})
                    insert_runbook = then_action.get('insert_runbook')
                    
                    if insert_runbook:
                        return {
                            'runbook': insert_runbook,
                            'stage': then_action.get('at_stage', self.current_stage + 0.5),
                            'name': 'Conditional Insertion',
                            'description': then_action.get('description', ''),
                            'hitl_checkpoint': True,  # Always checkpoint conditional insertions
                            'required': False
                        }
        
        return None
    
    def _pattern_matches_findings(self, pattern: str, findings: Dict[str, Any]) -> bool:
        """Check if a pattern (with | for OR) matches in findings"""
        import re
        
        patterns = [p.strip() for p in pattern.split('|')]
        
        for p in patterns:
            for key, value in findings.items():
                value_str = str(value).lower()
                if p.lower() in value_str or p.lower() in key.lower():
                    return True
        
        return False
    
    def complete_stage(self, stage: int, findings: Dict[str, Any]):
        """Mark a stage as complete and record its findings"""
        if stage not in self.completed_stages:
            self.completed_stages.append(stage)
        
        self.playbook_findings[stage] = findings
        
        # Also record in flow manager for runbook-level tracking
        if self.current_playbook:
            playbook = self.loaded_playbooks[self.current_playbook]
            sequence = playbook['sequence']
            
            # Find runbook name for this stage
            for item in sequence:
                if item['stage'] == stage:
                    runbook_name = item['runbook']
                    self.flow_manager.record_runbook_completion(runbook_name, findings)
                    break
    
    def is_playbook_complete(self) -> bool:
        """Check if all required stages are complete"""
        if not self.current_playbook:
            return False
        
        playbook = self.loaded_playbooks[self.current_playbook]
        sequence = playbook['sequence']
        
        for item in sequence:
            if item.get('required', True):
                if item['stage'] not in self.completed_stages:
                    return False
        
        return True
    
    def check_failure_criteria(self) -> tuple[bool, str]:
        """
        Check if playbook should be aborted due to failure criteria
        Returns: (should_abort: bool, reason: str)
        """
        if not self.current_playbook:
            return (False, "")
        
        playbook = self.loaded_playbooks[self.current_playbook]
        failure_criteria = playbook.get('failure_criteria', [])
        
        # For now, simple string matching in findings
        # In production, implement more sophisticated evaluation
        for criterion in failure_criteria:
            criterion_lower = criterion.lower()
            
            # Check in latest findings
            if self.playbook_findings:
                latest_stage = max(self.playbook_findings.keys())
                latest_findings = self.playbook_findings[latest_stage]
                
                for key, value in latest_findings.items():
                    value_str = str(value).lower()
                    if criterion_lower in value_str or criterion_lower in key.lower():
                        return (True, criterion)
        
        return (False, "")
    
    def get_playbook_summary(self) -> Dict[str, Any]:
        """
        Get summary of playbook execution state
        Returns: detailed status dict
        """
        if not self.current_playbook:
            return {'status': 'no_active_playbook'}
        
        playbook = self.loaded_playbooks[self.current_playbook]
        sequence = self.get_runbook_sequence(self.current_playbook)
        
        return {
            'playbook_name': playbook['metadata']['name'],
            'current_stage': self.current_stage,
            'completed_stages': self.completed_stages,
            'total_stages': len(sequence),
            'progress_percent': (len(self.completed_stages) / len(sequence) * 100) if sequence else 0,
            'is_complete': self.is_playbook_complete(),
            'findings_count': sum(len(f) for f in self.playbook_findings.values()),
            'next_runbook': self.get_next_runbook()
        }
