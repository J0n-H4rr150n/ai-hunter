"""
Runbook Parser and Executor
Parses YAML runbooks and integrates with tactical planning
"""

import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any

class RunbookParser:
    """Parse and validate YAML runbooks"""
    
    def __init__(self, runbooks_dir: str = "runbooks"):
        self.runbooks_dir = Path(runbooks_dir)
        self.loaded_runbooks = {}
    
    def load_runbook(self, runbook_name: str) -> Dict[str, Any]:
        """Load a runbook from YAML file"""
        runbook_path = self.runbooks_dir / f"{runbook_name}.yaml"
        
        if not runbook_path.exists():
            raise FileNotFoundError(f"Runbook not found: {runbook_path}")
        
        with open(runbook_path, 'r') as f:
            runbook = yaml.safe_load(f)
        
        # Validate runbook structure
        self._validate_runbook(runbook)
        
        # Cache it
        self.loaded_runbooks[runbook_name] = runbook
        
        return runbook
    
    def _validate_runbook(self, runbook: dict):
        """Validate runbook has required fields"""
        required_fields = ['metadata', 'steps']
        
        for field in required_fields:
            if field not in runbook:
                raise ValueError(f"Runbook missing required field: {field}")
        
        # Validate metadata
        if 'name' not in runbook['metadata']:
            raise ValueError("Runbook metadata missing 'name'")
        
        # Validate steps
        if not isinstance(runbook['steps'], list) or len(runbook['steps']) == 0:
            raise ValueError("Runbook must have at least one step")
        
        # Validate each step
        for step in runbook['steps']:
            required_step_fields = ['id', 'name', 'action', 'description']
            for field in required_step_fields:
                if field not in step:
                    raise ValueError(f"Step missing required field: {field}")
    
    def get_step(self, runbook: dict, step_id: str) -> Optional[Dict]:
        """Get a specific step by ID"""
        for step in runbook['steps']:
            if step['id'] == step_id:
                return step
        return None
    
    def get_steps_in_order(self, runbook: dict) -> List[Dict]:
        """Get steps in dependency order"""
        steps = runbook['steps']
        ordered_steps = []
        completed_ids = set()
        
        # Simple topological sort
        max_iterations = len(steps) * 2
        iteration = 0
        
        while len(ordered_steps) < len(steps) and iteration < max_iterations:
            iteration += 1
            
            for step in steps:
                if step['id'] in completed_ids:
                    continue
                
                # Check if dependencies are met
                depends_on = step.get('depends_on', [])
                if all(dep in completed_ids for dep in depends_on):
                    ordered_steps.append(step)
                    completed_ids.add(step['id'])
        
        if len(ordered_steps) < len(steps):
            raise ValueError("Circular dependency detected in runbook steps")
        
        return ordered_steps
    
    def format_runbook_for_llm(self, runbook: dict, include_findings: bool = True) -> str:
        """Format runbook into text that LLM can use for plan generation"""
        metadata = runbook['metadata']
        steps = runbook['steps']
        
        formatted = f"""# {metadata['name']}
{metadata.get('description', '')}

## Reconnaissance Steps
"""
        
        for i, step in enumerate(steps, 1):
            formatted += f"\n### Step {i}: {step['name']}\n"
            formatted += f"**Action:** {step['action']}\n"
            formatted += f"**Description:** {step['description']}\n"
            
            if 'tool' in step:
                formatted += f"**Tool:** {step['tool']}\n"
            
            if include_findings and 'findings_to_log' in step:
                formatted += f"**Expected Findings:**\n"
                for finding in step['findings_to_log']:
                    formatted += f"- {finding}\n"
            
            if 'depends_on' in step and step['depends_on']:
                formatted += f"**Prerequisites:** {', '.join(step['depends_on'])}\n"
        
        # Add analysis section if present
        if 'analysis' in runbook:
            formatted += "\n## Analysis & Planning\n"
            for analysis_step in runbook['analysis']:
                formatted += f"\n### {analysis_step['name']}\n"
                formatted += f"{analysis_step['description']}\n"
                
                if 'strategy' in analysis_step:
                    formatted += "\n**Strategy:**\n"
                    for strategy_point in analysis_step['strategy']:
                        formatted += f"- {strategy_point}\n"
        
        # Add success criteria
        if 'success_criteria' in runbook:
            formatted += "\n## Success Criteria\n"
            for criterion in runbook['success_criteria']:
                formatted += f"- {criterion}\n"
        
        return formatted


class RunbookExecutor:
    """Execute runbook steps and track findings"""
    
    def __init__(self, runbook: dict, findings_repo):
        self.runbook = runbook
        self.findings_repo = findings_repo
        self.completed_steps = set()
        self.step_findings = {}  # step_id -> findings dict
    
    def record_step_findings(self, step_id: str, findings: Dict[str, Any]):
        """Record findings from a completed step"""
        self.step_findings[step_id] = findings
        self.completed_steps.add(step_id)
        
        # Also save to findings repository
        self.findings_repo.save_finding(
            content={
                'runbook': self.runbook['metadata']['name'],
                'step_id': step_id,
                'step_name': self._get_step_name(step_id),
                'findings': findings
            },
            finding_type='runbook_step_findings',
            source='RunbookExecutor',
            tags=['runbook', step_id, self.runbook['metadata']['name']]
        )
    
    def _get_step_name(self, step_id: str) -> str:
        """Get step name by ID"""
        for step in self.runbook['steps']:
            if step['id'] == step_id:
                return step['name']
        return step_id
    
    def get_all_findings(self) -> Dict[str, Any]:
        """Get all findings from all completed steps"""
        return self.step_findings.copy()
    
    def get_findings_summary(self) -> str:
        """Generate a summary of all findings for LLM context"""
        summary = f"# Findings from {self.runbook['metadata']['name']}\n\n"
        
        for step_id, findings in self.step_findings.items():
            step_name = self._get_step_name(step_id)
            summary += f"## {step_name}\n"
            
            # Format findings
            for key, value in findings.items():
                if isinstance(value, list):
                    summary += f"**{key.replace('_', ' ').title()}:**\n"
                    for item in value[:10]:  # Limit to first 10 items
                        summary += f"- {item}\n"
                    if len(value) > 10:
                        summary += f"- ... and {len(value) - 10} more\n"
                else:
                    summary += f"**{key.replace('_', ' ').title()}:** {value}\n"
            
            summary += "\n"
        
        return summary
    
    def is_complete(self) -> bool:
        """Check if all steps are completed"""
        total_steps = len(self.runbook['steps'])
        return len(self.completed_steps) >= total_steps
    
    def get_next_step(self) -> Optional[Dict]:
        """Get next step to execute based on dependencies"""
        parser = RunbookParser()
        ordered_steps = parser.get_steps_in_order(self.runbook)
        
        for step in ordered_steps:
            if step['id'] not in self.completed_steps:
                # Check dependencies
                depends_on = step.get('depends_on', [])
                if all(dep in self.completed_steps for dep in depends_on):
                    return step
        
        return None  # All steps complete or blocked
