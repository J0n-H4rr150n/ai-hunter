"""
Validation System for Playbooks and Runbooks
Validates structure, dependencies, and paths before execution
"""

import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum


class ValidationSeverity(Enum):
    """Severity levels for validation issues"""
    ERROR = "error"      # Blocks execution
    WARNING = "warning"  # Suggests fix but allows execution
    INFO = "info"        # Informational only


class ValidationIssue:
    """Represents a single validation issue"""
    
    def __init__(self, severity: ValidationSeverity, category: str, message: str, 
                 location: str = "", suggestion: str = ""):
        self.severity = severity
        self.category = category
        self.message = message
        self.location = location
        self.suggestion = suggestion
    
    def __repr__(self):
        loc = f" at {self.location}" if self.location else ""
        sug = f"\n  Suggestion: {self.suggestion}" if self.suggestion else ""
        return f"[{self.severity.value.upper()}] {self.category}{loc}: {self.message}{sug}"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'severity': self.severity.value,
            'category': self.category,
            'message': self.message,
            'location': self.location,
            'suggestion': self.suggestion
        }


class ValidationResult:
    """Result of validation with all issues found"""
    
    def __init__(self):
        self.issues: List[ValidationIssue] = []
    
    def add_error(self, category: str, message: str, location: str = "", suggestion: str = ""):
        self.issues.append(ValidationIssue(ValidationSeverity.ERROR, category, message, location, suggestion))
    
    def add_warning(self, category: str, message: str, location: str = "", suggestion: str = ""):
        self.issues.append(ValidationIssue(ValidationSeverity.WARNING, category, message, location, suggestion))
    
    def add_info(self, category: str, message: str, location: str = "", suggestion: str = ""):
        self.issues.append(ValidationIssue(ValidationSeverity.INFO, category, message, location, suggestion))
    
    def has_errors(self) -> bool:
        return any(issue.severity == ValidationSeverity.ERROR for issue in self.issues)
    
    def has_warnings(self) -> bool:
        return any(issue.severity == ValidationSeverity.WARNING for issue in self.issues)
    
    def is_valid(self) -> bool:
        """Returns True if no errors (warnings are OK)"""
        return not self.has_errors()
    
    def get_errors(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.ERROR]
    
    def get_warnings(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == ValidationSeverity.WARNING]
    
    def summary(self) -> str:
        errors = len(self.get_errors())
        warnings = len(self.get_warnings())
        
        if errors == 0 and warnings == 0:
            return "✅ Validation passed"
        
        parts = []
        if errors > 0:
            parts.append(f"❌ {errors} error(s)")
        if warnings > 0:
            parts.append(f"⚠️  {warnings} warning(s)")
        
        return ", ".join(parts)
    
    def __str__(self):
        lines = [self.summary()]
        for issue in self.issues:
            lines.append(f"  {issue}")
        return "\n".join(lines)


class RunbookValidator:
    """Validates runbook YAML structure and dependencies"""
    
    def __init__(self, runbooks_dir: str = "runbooks"):
        self.runbooks_dir = Path(runbooks_dir)
    
    def validate_runbook(self, runbook_name: str) -> ValidationResult:
        """Validate a single runbook"""
        result = ValidationResult()
        
        # Check file exists
        runbook_path = self.runbooks_dir / f"{runbook_name}.yaml"
        if not runbook_path.exists():
            result.add_error(
                "FileNotFound",
                f"Runbook file does not exist: {runbook_path}",
                suggestion="Check the runbook name and ensure the file exists in the runbooks directory"
            )
            return result
        
        # Load YAML
        try:
            with open(runbook_path, 'r', encoding='utf-8') as f:
                runbook = yaml.safe_load(f)
        except yaml.YAMLError as e:
            result.add_error(
                "InvalidYAML",
                f"Failed to parse YAML: {e}",
                location=str(runbook_path),
                suggestion="Fix YAML syntax errors"
            )
            return result
        except Exception as e:
            result.add_error(
                "FileReadError",
                f"Failed to read file: {e}",
                location=str(runbook_path)
            )
            return result
        
        # Validate structure
        self._validate_structure(runbook, runbook_name, result)
        self._validate_metadata(runbook, result)
        self._validate_steps(runbook, result)
        self._validate_dependencies(runbook, result)
        
        return result
    
    def _validate_structure(self, runbook: dict, runbook_name: str, result: ValidationResult):
        """Validate top-level structure"""
        required_fields = ['metadata', 'steps']
        
        for field in required_fields:
            if field not in runbook:
                result.add_error(
                    "MissingRequiredField",
                    f"Runbook missing required top-level field: '{field}'",
                    location=runbook_name,
                    suggestion=f"Add '{field}:' section to the runbook"
                )
    
    def _validate_metadata(self, runbook: dict, result: ValidationResult):
        """Validate metadata section"""
        if 'metadata' not in runbook:
            return
        
        metadata = runbook['metadata']
        
        # Required fields
        if 'name' not in metadata:
            result.add_error(
                "MissingMetadata",
                "metadata.name is required",
                suggestion="Add 'name: \"Runbook Name\"' to metadata"
            )
        
        # Recommended fields
        recommended = ['version', 'description', 'author']
        for field in recommended:
            if field not in metadata:
                result.add_warning(
                    "MissingRecommendedField",
                    f"metadata.{field} is recommended but missing",
                    suggestion=f"Add '{field}:' to metadata for better documentation"
                )
        
        # Validate v2.0 flow fields if present
        if 'prerequisites' in metadata:
            prereqs = metadata['prerequisites']
            if not isinstance(prereqs, dict):
                result.add_error(
                    "InvalidStructure",
                    "metadata.prerequisites must be a dict with 'required' and 'optional' keys",
                    location="metadata.prerequisites"
                )
            else:
                if 'required' in prereqs and not isinstance(prereqs['required'], list):
                    result.add_error(
                        "InvalidType",
                        "metadata.prerequisites.required must be a list",
                        location="metadata.prerequisites.required"
                    )
                if 'optional' in prereqs and not isinstance(prereqs['optional'], list):
                    result.add_error(
                        "InvalidType",
                        "metadata.prerequisites.optional must be a list",
                        location="metadata.prerequisites.optional"
                    )
        
        if 'triggers' in metadata:
            if not isinstance(metadata['triggers'], list):
                result.add_error(
                    "InvalidType",
                    "metadata.triggers must be a list",
                    location="metadata.triggers"
                )
    
    def _validate_steps(self, runbook: dict, result: ValidationResult):
        """Validate steps section"""
        if 'steps' not in runbook:
            return
        
        steps = runbook['steps']
        
        if not isinstance(steps, list):
            result.add_error(
                "InvalidType",
                "steps must be a list",
                location="steps"
            )
            return
        
        if len(steps) == 0:
            result.add_error(
                "EmptySteps",
                "Runbook must have at least one step",
                location="steps",
                suggestion="Add at least one step to the runbook"
            )
            return
        
        step_ids = set()
        
        for i, step in enumerate(steps):
            location = f"steps[{i}]"
            
            # Always required fields
            required_fields = ['id', 'name', 'description']
            for field in required_fields:
                if field not in step:
                    result.add_error(
                        "MissingStepField",
                        f"Step missing required field: '{field}'",
                        location=location,
                        suggestion=f"Add '{field}:' to the step"
                    )
            
            # Action is required unless step is agent_guided
            agent_mode = step.get('agent_mode')
            if agent_mode != 'agent_guided' and 'action' not in step:
                result.add_error(
                    "MissingStepField",
                    f"Step missing required field: 'action' (not needed for agent_guided steps)",
                    location=location,
                    suggestion="Add 'action:' to the step or set 'agent_mode: agent_guided'"
                )
            
            # Check for duplicate IDs
            if 'id' in step:
                step_id = step['id']
                if step_id in step_ids:
                    result.add_error(
                        "DuplicateStepID",
                        f"Duplicate step ID: '{step_id}'",
                        location=location,
                        suggestion="Each step must have a unique ID"
                    )
                step_ids.add(step_id)
            
            # Recommended fields
            if 'tool' not in step:
                result.add_warning(
                    "MissingRecommendedField",
                    f"Step '{step.get('id', i)}' missing 'tool' field",
                    location=location,
                    suggestion="Specify which tool this step uses"
                )
    
    def _validate_dependencies(self, runbook: dict, result: ValidationResult):
        """Validate step dependencies and detect cycles"""
        if 'steps' not in runbook:
            return
        
        steps = runbook['steps']
        step_ids = {step.get('id') for step in steps if 'id' in step}
        
        # Check depends_on references
        for i, step in enumerate(steps):
            step_id = step.get('id', f'step_{i}')
            depends_on = step.get('depends_on', [])
            
            if not isinstance(depends_on, list):
                result.add_error(
                    "InvalidType",
                    f"Step '{step_id}' depends_on must be a list",
                    location=f"steps[{i}].depends_on"
                )
                continue
            
            for dep in depends_on:
                if dep not in step_ids:
                    result.add_error(
                        "InvalidDependency",
                        f"Step '{step_id}' depends on non-existent step: '{dep}'",
                        location=f"steps[{i}].depends_on",
                        suggestion=f"Ensure step with id '{dep}' exists or remove this dependency"
                    )
        
        # Detect circular dependencies
        if self._has_circular_dependency(steps):
            result.add_error(
                "CircularDependency",
                "Circular dependency detected in runbook steps",
                location="steps",
                suggestion="Review depends_on relationships to remove cycles"
            )
    
    def _has_circular_dependency(self, steps: List[dict]) -> bool:
        """Detect circular dependencies using DFS"""
        # Build adjacency list
        graph = {}
        for step in steps:
            step_id = step.get('id')
            if step_id:
                graph[step_id] = step.get('depends_on', [])
        
        # DFS to detect cycle
        visited = set()
        rec_stack = set()
        
        def has_cycle(node):
            visited.add(node)
            rec_stack.add(node)
            
            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if has_cycle(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            
            rec_stack.remove(node)
            return False
        
        for node in graph:
            if node not in visited:
                if has_cycle(node):
                    return True
        
        return False


class PlaybookValidator:
    """Validates playbook YAML structure and runbook references"""
    
    def __init__(self, playbooks_dir: str = "playbooks", runbooks_dir: str = "runbooks"):
        self.playbooks_dir = Path(playbooks_dir)
        self.runbooks_dir = Path(runbooks_dir)
        self.runbook_validator = RunbookValidator(runbooks_dir)
    
    def validate_playbook(self, playbook_name: str) -> ValidationResult:
        """Validate a complete playbook and all referenced runbooks"""
        result = ValidationResult()
        
        # Check file exists
        playbook_path = self.playbooks_dir / f"{playbook_name}.yaml"
        if not playbook_path.exists():
            result.add_error(
                "FileNotFound",
                f"Playbook file does not exist: {playbook_path}",
                suggestion="Check the playbook name and ensure the file exists in the playbooks directory"
            )
            return result
        
        # Load YAML
        try:
            with open(playbook_path, 'r', encoding='utf-8') as f:
                playbook = yaml.safe_load(f)
        except yaml.YAMLError as e:
            result.add_error(
                "InvalidYAML",
                f"Failed to parse YAML: {e}",
                location=str(playbook_path),
                suggestion="Fix YAML syntax errors"
            )
            return result
        except Exception as e:
            result.add_error(
                "FileReadError",
                f"Failed to read file: {e}",
                location=str(playbook_path)
            )
            return result
        
        # Validate playbook structure
        self._validate_structure(playbook, playbook_name, result)
        self._validate_metadata(playbook, result)
        self._validate_sequence(playbook, result)
        
        # Validate all referenced runbooks
        if 'sequence' in playbook and isinstance(playbook['sequence'], list):
            self._validate_runbook_references(playbook, result)
        
        return result
    
    def _validate_structure(self, playbook: dict, playbook_name: str, result: ValidationResult):
        """Validate top-level playbook structure"""
        required_fields = ['metadata', 'sequence']
        
        for field in required_fields:
            if field not in playbook:
                result.add_error(
                    "MissingRequiredField",
                    f"Playbook missing required top-level field: '{field}'",
                    location=playbook_name,
                    suggestion=f"Add '{field}:' section to the playbook"
                )
    
    def _validate_metadata(self, playbook: dict, result: ValidationResult):
        """Validate playbook metadata"""
        if 'metadata' not in playbook:
            return
        
        metadata = playbook['metadata']
        
        # Required
        if 'name' not in metadata:
            result.add_error(
                "MissingMetadata",
                "metadata.name is required",
                suggestion="Add 'name: \"Playbook Name\"' to metadata"
            )
        
        # Recommended
        recommended = ['description', 'objective', 'category']
        for field in recommended:
            if field not in metadata:
                result.add_warning(
                    "MissingRecommendedField",
                    f"metadata.{field} is recommended but missing",
                    suggestion=f"Add '{field}:' to metadata"
                )
    
    def _validate_sequence(self, playbook: dict, result: ValidationResult):
        """Validate runbook sequence"""
        if 'sequence' not in playbook:
            return
        
        sequence = playbook['sequence']
        
        if not isinstance(sequence, list):
            result.add_error(
                "InvalidType",
                "sequence must be a list",
                location="sequence"
            )
            return
        
        if len(sequence) == 0:
            result.add_error(
                "EmptySequence",
                "Playbook must have at least one runbook in sequence",
                location="sequence",
                suggestion="Add at least one runbook to the sequence"
            )
            return
        
        stages = set()
        
        for i, item in enumerate(sequence):
            location = f"sequence[{i}]"
            
            # Required fields
            if 'runbook' not in item:
                result.add_error(
                    "MissingField",
                    "Sequence item missing 'runbook' field",
                    location=location,
                    suggestion="Add 'runbook: runbook_name' to this sequence item"
                )
            
            if 'stage' not in item:
                result.add_error(
                    "MissingField",
                    "Sequence item missing 'stage' field",
                    location=location,
                    suggestion="Add 'stage: N' to this sequence item"
                )
            else:
                stage = item['stage']
                if stage in stages:
                    result.add_warning(
                        "DuplicateStage",
                        f"Duplicate stage number: {stage}",
                        location=location,
                        suggestion="Consider using unique stage numbers (e.g., 1, 2, 3) or decimals (2.5) for insertions"
                    )
                stages.add(stage)
    
    def _validate_runbook_references(self, playbook: dict, result: ValidationResult):
        """Validate that all referenced runbooks exist and are valid"""
        sequence = playbook['sequence']
        
        for i, item in enumerate(sequence):
            if 'runbook' not in item:
                continue
            
            runbook_name = item['runbook']
            location = f"sequence[{i}].runbook"
            
            # Check if runbook file exists
            runbook_path = self.runbooks_dir / f"{runbook_name}.yaml"
            if not runbook_path.exists():
                result.add_error(
                    "RunbookNotFound",
                    f"Referenced runbook does not exist: '{runbook_name}'",
                    location=location,
                    suggestion=f"Create {runbook_path} or fix the runbook name"
                )
                continue
            
            # Validate the runbook itself
            runbook_result = self.runbook_validator.validate_runbook(runbook_name)
            
            # Add runbook errors as playbook errors
            for issue in runbook_result.get_errors():
                result.add_error(
                    f"RunbookError:{runbook_name}",
                    issue.message,
                    location=f"{location} -> {issue.location}",
                    suggestion=issue.suggestion
                )
            
            # Add runbook warnings as playbook warnings
            for issue in runbook_result.get_warnings():
                result.add_warning(
                    f"RunbookWarning:{runbook_name}",
                    issue.message,
                    location=f"{location} -> {issue.location}",
                    suggestion=issue.suggestion
                )
