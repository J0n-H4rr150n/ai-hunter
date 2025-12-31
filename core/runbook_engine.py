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
        metadata = runbook['metadata']
        if 'name' not in metadata:
            raise ValueError("Runbook metadata missing 'name'")
        
        # Validate v2.0 flow fields (optional but if present must be valid)
        if 'prerequisites' in metadata:
            prereqs = metadata['prerequisites']
            if not isinstance(prereqs, dict):
                raise ValueError("prerequisites must be a dict with 'required' and 'optional' keys")
            if 'required' in prereqs and not isinstance(prereqs['required'], list):
                raise ValueError("prerequisites.required must be a list")
            if 'optional' in prereqs and not isinstance(prereqs['optional'], list):
                raise ValueError("prerequisites.optional must be a list")
        
        if 'triggers' in metadata:
            if not isinstance(metadata['triggers'], list):
                raise ValueError("triggers must be a list")
        
        if 'next_runbooks' in metadata:
            next_rbs = metadata['next_runbooks']
            if not isinstance(next_rbs, dict):
                raise ValueError("next_runbooks must be a dict")
        
        # Validate steps
        if not isinstance(runbook['steps'], list) or len(runbook['steps']) == 0:
            raise ValueError("Runbook must have at least one step")
        
        # Validate each step
        for step in runbook['steps']:
            # Always required fields
            required_step_fields = ['id', 'name', 'description']
            for field in required_step_fields:
                if field not in step:
                    raise ValueError(f"Step missing required field: {field}")
            
            # Action is required unless step is agent_guided
            agent_mode = step.get('agent_mode')
            if agent_mode != 'agent_guided' and 'action' not in step:
                raise ValueError(f"Step missing required field: 'action' (not needed for agent_guided steps)")
    
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
            if 'action' in step:
                formatted += f"**Action:** {step['action']}\n"
            elif step.get('agent_mode') == 'agent_guided':
                formatted += f"**Mode:** Agent-guided (LLM decides actions)\n"
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


class RunbookFlowManager:
    """Manage runbook execution flow, dependencies, and transitions"""
    
    def __init__(self, parser: RunbookParser):
        self.parser = parser
        self.execution_history = []  # List of completed runbook names
        self.findings_db = {}  # runbook_name -> findings dict
        self.all_findings = {}  # Flat dict of all findings across runbooks
    
    def record_runbook_completion(self, runbook_name: str, findings: Dict[str, Any]):
        """Record that a runbook has been completed with its findings"""
        if runbook_name not in self.execution_history:
            self.execution_history.append(runbook_name)
        
        self.findings_db[runbook_name] = findings
        
        # Merge findings into flat structure for pattern matching
        for key, value in findings.items():
            if key not in self.all_findings:
                self.all_findings[key] = []
            if isinstance(value, list):
                self.all_findings[key].extend(value)
            else:
                self.all_findings[key].append(value)
    
    def check_prerequisites(self, runbook_name: str) -> tuple[bool, List[str]]:
        """
        Check if prerequisites are met for a runbook
        Returns: (ready: bool, missing_prereqs: List[str])
        """
        try:
            runbook = self.parser.load_runbook(runbook_name)
        except FileNotFoundError:
            return (False, [f"Runbook '{runbook_name}' not found"])
        
        metadata = runbook.get('metadata', {})
        prerequisites = metadata.get('prerequisites', {})
        
        required = prerequisites.get('required', [])
        missing = []
        
        for prereq in required:
            if prereq not in self.execution_history:
                missing.append(prereq)
        
        return (len(missing) == 0, missing)
    
    def get_eligible_runbooks(self, runbook_names: List[str] = None) -> List[Dict]:
        """
        Get runbooks whose prerequisites are satisfied
        If runbook_names provided, check only those; otherwise check all in runbooks dir
        """
        if runbook_names is None:
            # Discover all runbooks in directory
            runbook_names = []
            for yaml_file in self.parser.runbooks_dir.glob("*.yaml"):
                runbook_names.append(yaml_file.stem)
        
        eligible = []
        for rb_name in runbook_names:
            if rb_name in self.execution_history:
                continue  # Already completed
            
            ready, missing = self.check_prerequisites(rb_name)
            if ready:
                eligible.append({
                    'name': rb_name,
                    'triggers_confidence': self.evaluate_triggers(rb_name)
                })
        
        # Sort by trigger confidence
        eligible.sort(key=lambda x: x['triggers_confidence'], reverse=True)
        return eligible
    
    def evaluate_triggers(self, runbook_name: str) -> float:
        """
        Evaluate if triggers match current findings
        Returns confidence score 0.0-1.0
        """
        try:
            runbook = self.parser.load_runbook(runbook_name)
        except FileNotFoundError:
            return 0.0
        
        metadata = runbook.get('metadata', {})
        triggers = metadata.get('triggers', [])
        
        if not triggers:
            return 0.5  # No triggers = neutral confidence
        
        total_confidence = 0.0
        trigger_count = 0
        
        for trigger in triggers:
            trigger_type = trigger.get('type', '')
            
            if trigger_type == 'manual':
                # Manual triggers don't auto-activate
                continue
            
            elif trigger_type == 'finding_match':
                patterns = trigger.get('patterns', [])
                source_runbook = trigger.get('source_runbook', '')
                base_confidence = trigger.get('confidence', 0.5)
                
                # Check if source runbook was completed
                if source_runbook and source_runbook not in self.execution_history:
                    continue
                
                # Check if any patterns match findings
                import re
                matched = False
                for pattern in patterns:
                    pattern_str = str(pattern)
                    # Search through all findings
                    for finding_key, finding_values in self.all_findings.items():
                        for val in finding_values:
                            val_str = str(val)
                            # Try literal match and regex match
                            if pattern_str.lower() in val_str.lower():
                                matched = True
                                break
                            try:
                                if re.search(pattern_str, val_str, re.IGNORECASE):
                                    matched = True
                                    break
                            except re.error:
                                pass  # Not a valid regex, skip
                        if matched:
                            break
                    if matched:
                        break
                
                if matched:
                    total_confidence += base_confidence
                    trigger_count += 1
        
        if trigger_count == 0:
            return 0.0
        
        # Return average confidence of matched triggers
        return min(total_confidence / trigger_count, 1.0)
    
    def suggest_next_runbooks(self, current_runbook: str, findings: Dict[str, Any]) -> List[Dict]:
        """
        Based on current runbook & findings, suggest next runbooks
        Returns list of dicts with: {name, condition, priority, description, confidence}
        """
        try:
            runbook = self.parser.load_runbook(current_runbook)
        except FileNotFoundError:
            return []
        
        # Record completion first
        self.record_runbook_completion(current_runbook, findings)
        
        metadata = runbook.get('metadata', {})
        next_runbooks = metadata.get('next_runbooks', {})
        
        suggestions = []
        
        # Check on_success conditions
        for next_rb in next_runbooks.get('on_success', []):
            condition = next_rb.get('condition', '')
            if self._evaluate_condition(condition, findings):
                suggestions.append({
                    'name': next_rb['runbook'],
                    'condition': condition,
                    'priority': next_rb.get('priority', 'medium'),
                    'description': next_rb.get('description', ''),
                    'reason': 'success_condition_met',
                    'confidence': 0.8
                })
        
        # Check on_failure conditions
        for next_rb in next_runbooks.get('on_failure', []):
            condition = next_rb.get('condition', '')
            if self._evaluate_condition(condition, findings):
                suggestions.append({
                    'name': next_rb['runbook'],
                    'condition': condition,
                    'priority': next_rb.get('priority', 'medium'),
                    'description': next_rb.get('description', ''),
                    'reason': 'failure_condition_met',
                    'confidence': 0.6
                })
        
        # Always suggestions (baseline)
        for next_rb in next_runbooks.get('always', []):
            suggestions.append({
                'name': next_rb['runbook'],
                'condition': 'always',
                'priority': next_rb.get('priority', 'low'),
                'description': next_rb.get('description', ''),
                'reason': 'baseline_suggestion',
                'confidence': 0.3
            })
        
        # Filter out runbooks with unmet prerequisites
        filtered_suggestions = []
        for suggestion in suggestions:
            ready, missing = self.check_prerequisites(suggestion['name'])
            if ready:
                filtered_suggestions.append(suggestion)
            else:
                # Add note about missing prerequisites
                suggestion['blocked'] = True
                suggestion['missing_prerequisites'] = missing
                filtered_suggestions.append(suggestion)
        
        # Sort by priority (high > medium > low) then confidence
        priority_order = {'high': 3, 'medium': 2, 'low': 1}
        filtered_suggestions.sort(
            key=lambda x: (priority_order.get(x.get('priority', 'low'), 0), x.get('confidence', 0)),
            reverse=True
        )
        
        return filtered_suggestions
    
    def _evaluate_condition(self, condition: str, findings: Dict[str, Any]) -> bool:
        """
        Evaluate if a condition is met based on findings
        Simple heuristic: check if condition string appears in findings keys/values
        """
        if not condition or condition == 'always':
            return True
        
        condition_lower = condition.lower().replace('_', ' ')
        
        # Check in findings keys
        for key in findings.keys():
            if condition_lower in key.lower().replace('_', ' '):
                return True
        
        # Check in findings values
        for value in findings.values():
            value_str = str(value).lower()
            if condition_lower in value_str:
                return True
        
        return False
    
    def build_execution_graph(self) -> Dict[str, Any]:
        """
        Build a dependency graph of all runbooks for visualization
        Returns dict suitable for graph rendering
        """
        # Discover all runbooks
        all_runbooks = []
        for yaml_file in self.parser.runbooks_dir.glob("*.yaml"):
            all_runbooks.append(yaml_file.stem)
        
        graph = {
            'nodes': [],
            'edges': []
        }
        
        for rb_name in all_runbooks:
            try:
                runbook = self.parser.load_runbook(rb_name)
                metadata = runbook.get('metadata', {})
                
                # Add node
                graph['nodes'].append({
                    'id': rb_name,
                    'label': metadata.get('name', rb_name),
                    'completed': rb_name in self.execution_history
                })
                
                # Add prerequisite edges
                prerequisites = metadata.get('prerequisites', {})
                for prereq in prerequisites.get('required', []):
                    graph['edges'].append({
                        'from': prereq,
                        'to': rb_name,
                        'type': 'prerequisite',
                        'required': True
                    })
                
                for prereq in prerequisites.get('optional', []):
                    graph['edges'].append({
                        'from': prereq,
                        'to': rb_name,
                        'type': 'prerequisite',
                        'required': False
                    })
                
                # Add next_runbook edges
                next_runbooks = metadata.get('next_runbooks', {})
                for next_rb in next_runbooks.get('on_success', []):
                    graph['edges'].append({
                        'from': rb_name,
                        'to': next_rb['runbook'],
                        'type': 'next_on_success',
                        'priority': next_rb.get('priority', 'medium')
                    })
                
            except Exception as e:
                print(f"Warning: Could not load runbook {rb_name}: {e}")
        
        return graph
