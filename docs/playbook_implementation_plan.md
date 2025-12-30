# Playbook/Runbook System - Complete Implementation Plan

**Status:** In Progress  
**Started:** December 30, 2025  
**Target Completion:** TBD  
**Priority:** HIGH - Core system enhancement

---

## Executive Summary

This plan outlines the complete integration of the playbooks/runbooks system into AI Hunter. The system provides declarative, YAML-based test automation with dynamic flow control, human-in-the-loop checkpoints, and intelligent chaining.

**Current Status:** 66% Complete (infrastructure built, integration pending)

**Key Components:**
- ✅ Runbook Parser & Engine (Complete)
- ✅ Playbook Manager (Complete)
- ✅ Validation System (Complete)
- ✅ State Management (Complete)
- ⚠️ Tool Implementation (20% - needs expansion)
- ❌ Execution Integration (0% - critical path)
- ❌ UI Integration (0% - user-facing)

---

## Phase 1: Core Playbook Executor Implementation

**Goal:** Create the execution engine that orchestrates playbook → runbook → steps → tools

### Task 1.1: Create PlaybookExecutor Class

**File:** `core/playbook_executor.py` (NEW)

```python
"""
Playbook Executor - Bridges playbooks/runbooks to autonomous execution
"""

from typing import Optional, Dict, Any, List
from core.playbook_manager import PlaybookManager
from core.runbook_engine import RunbookParser, RunbookExecutor
from core.state_manager import StateManager
from memory.finding_repository import FindingRepository

class PlaybookExecutor:
    """
    Executes playbooks by orchestrating runbooks and integrating with the agent.
    Handles HITL checkpoints, state management, and finding aggregation.
    """
    
    def __init__(self, autonomous_loop, db):
        self.loop = autonomous_loop
        self.db = db
        self.manager = PlaybookManager()
        self.state_manager = StateManager(db)
        self.finding_repo = autonomous_loop.repo
        
        # Execution state
        self.current_playbook = None
        self.current_runbook_executor = None
        self.mission_id = None
        
    async def execute_playbook(self, playbook_name: str, goal: str, 
                              target_url: str, mission_id: int) -> Dict[str, Any]:
        """
        Main entry point for playbook execution.
        Returns execution summary with findings.
        """
        pass  # Implementation details below
    
    async def _execute_runbook(self, runbook_name: str) -> Dict[str, Any]:
        """Execute a single runbook and return findings"""
        pass
    
    async def _execute_step(self, step: dict) -> Dict[str, Any]:
        """Execute a single runbook step"""
        pass
    
    def _map_action_to_tool(self, action: str, tool_name: str) -> callable:
        """Map runbook action to actual tool method"""
        pass
```

**Implementation Details:**

1. **Validation First:** Always call `self.manager.validate_playbook_preflight()` before execution
2. **State Tracking:** Store playbook progress in state_manager for pause/resume
3. **Finding Aggregation:** Collect findings from each step/runbook
4. **Error Handling:** Graceful failures with rollback support
5. **HITL Integration:** Call existing HITL callbacks at checkpoints

**Acceptance Criteria:**
- [ ] Can load and validate a playbook
- [ ] Executes runbooks in sequence order
- [ ] Handles conditional branching
- [ ] Respects HITL checkpoints
- [ ] Aggregates findings across runbooks
- [ ] Persists state to database

---

### Task 1.2: Integrate with AutonomousLoop

**File:** `core/autonomous_loop.py` (MODIFY)

Add new method alongside existing `start_mission()`:

```python
async def start_mission_with_playbook(self, playbook_name: str, goal: str, 
                                     target_url: str, instructions: str = None):
    """
    New execution path using playbook/runbook system.
    Co-exists with old tactical planner for backward compatibility.
    """
    
    self.log_to_ui(f"\n[Auto] 🎯 Starting Playbook Mission: {playbook_name}")
    self.log_to_ui(f"[Auto] 🚀 Goal: {goal}")
    self.log_to_ui(f"[Auto] 🌐 Target: {target_url}")
    
    # Initialize playbook executor
    self.playbook_executor = PlaybookExecutor(self, self.db)
    
    # Execute
    try:
        result = await self.playbook_executor.execute_playbook(
            playbook_name, goal, target_url, self.mission_id
        )
        
        self.log_to_ui(f"[Auto] ✅ Playbook complete: {result['summary']}")
        return result
        
    except Exception as e:
        self.log_to_ui(f"[Auto] ❌ Playbook execution failed: {e}")
        raise
```

**Migration Strategy:**
- Keep `start_mission()` (old tactical planner) working
- Add `start_mission_with_playbook()` as new path
- Frontend can choose which to use
- Eventually deprecate old path

**Acceptance Criteria:**
- [ ] Both mission modes work (old & new)
- [ ] Proper error handling and logging
- [ ] State cleanup on failure
- [ ] Browser lifecycle managed correctly

---

### Task 1.3: Database Schema Extensions

**File:** `alembic/versions/005_add_playbook_execution.py` (NEW)

Add tables for tracking playbook execution:

```python
"""
Add playbook execution tracking

Revision ID: 005
Revises: 004
"""

def upgrade():
    op.create_table(
        'playbook_executions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('mission_id', sa.Integer(), sa.ForeignKey('missions.id')),
        sa.Column('playbook_name', sa.String(255), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),  # running, completed, failed
        sa.Column('current_stage', sa.Integer(), nullable=True),
        sa.Column('findings_summary', postgresql.JSONB, nullable=True),
        sa.Column('started_at', sa.DateTime(), server_default=sa.text('NOW()')),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )
    
    op.create_table(
        'runbook_executions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('playbook_execution_id', sa.Integer(), 
                  sa.ForeignKey('playbook_executions.id')),
        sa.Column('runbook_name', sa.String(255), nullable=False),
        sa.Column('stage', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('findings', postgresql.JSONB, nullable=True),
        sa.Column('started_at', sa.DateTime(), server_default=sa.text('NOW()')),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )
```

**Purpose:** Track execution history for learning and debugging

---

## Phase 2: Tool Mapping and Implementation

**Goal:** Bridge runbook actions to concrete tool implementations

### Task 2.1: Create Action-to-Tool Mapper

**File:** `core/tool_mapper.py` (NEW)

```python
"""
Maps runbook actions to tool implementations
"""

from typing import Dict, Any, Callable
from tools.som_browser import SoMBrowser
from tools.tech_scanner import TechScanner
from tools.fuzzer import Fuzzer
from memory.finding_repository import FindingRepository

class ToolMapper:
    """
    Maps runbook actions (strings) to actual tool methods (callables).
    Handles parameter translation and result formatting.
    """
    
    def __init__(self, browser: SoMBrowser, scanner: TechScanner, 
                 fuzzer: Fuzzer, repo: FindingRepository):
        self.browser = browser
        self.scanner = scanner
        self.fuzzer = fuzzer
        self.repo = repo
        
        # Action mapping registry
        self.action_map = self._build_action_map()
    
    def _build_action_map(self) -> Dict[str, Callable]:
        """Build the action → tool method mapping"""
        return {
            # Browser actions
            'navigate': self._action_navigate,
            'click': self._action_click,
            'type': self._action_type,
            'view_source': self._action_view_source,
            'inspect_dom': self._action_inspect_dom,
            'monitor_network': self._action_monitor_network,
            'capture_screenshot': self._action_capture_screenshot,
            
            # Scanner actions
            'tech_scan': self._action_tech_scan,
            'fingerprint': self._action_fingerprint,
            
            # Fuzzer actions
            'fuzz_parameter': self._action_fuzz_parameter,
            'run_intruder': self._action_run_intruder,
            
            # Analysis actions
            'compile_findings': self._action_compile_findings,
            'pattern_search': self._action_pattern_search,
            'risk_assessment': self._action_risk_assessment,
            
            # HITL actions
            'request_approval': self._action_request_approval,
        }
    
    def execute_action(self, action: str, step: dict) -> Dict[str, Any]:
        """
        Execute a runbook action with the appropriate tool.
        Returns findings dict to be logged.
        """
        if action not in self.action_map:
            raise ValueError(f"Unknown action: {action}")
        
        handler = self.action_map[action]
        return handler(step)
    
    # Action handlers (one per action type)
    def _action_navigate(self, step: dict) -> Dict[str, Any]:
        """Navigate browser to URL"""
        url = step.get('url') or step.get('value')
        self.browser.navigate(url)
        return {
            'status': 'success',
            'url': url,
            'page_title': self.browser.driver.title
        }
    
    # ... implement all other action handlers
```

**Action Coverage Matrix:**

| Runbook Action | Tool | Method | Status |
|----------------|------|--------|--------|
| navigate | SoMBrowser | navigate() | ✅ Exists |
| click | SoMBrowser | click() | ✅ Exists |
| type | SoMBrowser | type_text() | ✅ Exists |
| view_source | SoMBrowser | get_raw_source() | ✅ Exists |
| inspect_dom | SoMBrowser | get_dom() | ✅ Exists |
| monitor_network | SoMBrowser | get_network_log() | ✅ Exists |
| capture_screenshot | SoMBrowser | shadow_capture() | ✅ Exists |
| tech_scan | TechScanner | comprehensive_scan() | ✅ Exists |
| fuzz_parameter | Fuzzer | smart_fuzz() | ✅ Exists |
| run_intruder | Fuzzer | run_intruder() | ✅ Exists |
| compile_findings | FindingRepository | search_findings() | ⚠️ Needs wrapper |
| pattern_search | FindingRepository | search_findings() | ⚠️ Needs wrapper |
| risk_assessment | NEW | - | ❌ To implement |
| request_approval | HumanInterface | request_tool_approval() | ✅ Exists |

**Acceptance Criteria:**
- [ ] All browser actions mapped
- [ ] All scanner actions mapped
- [ ] All fuzzer actions mapped
- [ ] Analysis actions implemented or stubbed
- [ ] Proper error handling and logging
- [ ] Parameter validation

---

### Task 2.2: Implement Missing Analysis Tools

**File:** `tools/findings_aggregator.py` (NEW)

```python
"""
Findings Aggregator - Compiles and analyzes findings across runbooks
"""

from typing import Dict, List, Any
from memory.finding_repository import FindingRepository

class FindingsAggregator:
    """Aggregates and analyzes findings from multiple runbooks"""
    
    def __init__(self, repo: FindingRepository):
        self.repo = repo
    
    def compile_findings(self, mission_id: int, filters: Dict = None) -> Dict[str, Any]:
        """Compile all findings for a mission"""
        findings = self.repo.search_findings(
            query="",  # Get all
            mission_id=mission_id,
            limit=1000
        )
        
        return {
            'total_findings': len(findings),
            'by_type': self._group_by_type(findings),
            'by_severity': self._group_by_severity(findings),
            'high_priority': self._filter_high_priority(findings),
            'timeline': self._build_timeline(findings)
        }
    
    def pattern_search(self, patterns: List[str], findings: List[Dict]) -> Dict[str, Any]:
        """Search for patterns in findings"""
        matches = []
        for pattern in patterns:
            for finding in findings:
                if self._matches_pattern(pattern, finding):
                    matches.append({
                        'pattern': pattern,
                        'finding': finding
                    })
        
        return {
            'patterns_found': len(set(m['pattern'] for m in matches)),
            'matches': matches
        }
    
    def assess_risk(self, findings: List[Dict]) -> Dict[str, Any]:
        """Assess overall risk based on findings"""
        # Implement CVSS-like scoring
        pass
```

**File:** `tools/report_generator.py` (NEW)

```python
"""
Report Generator - Creates formatted reports from findings
"""

class ReportGenerator:
    """Generates security reports in various formats"""
    
    def generate_executive_summary(self, findings: Dict) -> str:
        """Non-technical executive summary (markdown)"""
        pass
    
    def generate_technical_report(self, findings: Dict) -> str:
        """Detailed technical report with POCs (markdown)"""
        pass
    
    def generate_json_export(self, findings: Dict) -> str:
        """Machine-readable JSON export"""
        pass
```

**Acceptance Criteria:**
- [ ] FindingsAggregator compiles findings correctly
- [ ] Pattern search works with regex and literals
- [ ] Risk assessment produces severity ratings
- [ ] Reports generate valid markdown
- [ ] JSON export is valid and complete

---

## Phase 3: Agent-Runbook Integration

**Goal:** Make the agent understand and execute runbook steps

### Task 3.1: Extend VertexAgent with Runbook Context

**File:** `agents/agent_brain.py` (MODIFY)

Add new method to VertexAgent class:

```python
def plan_next_step_from_runbook(self, runbook_step: dict, goal: str, 
                                history: list, screenshot_bytes: bytes, 
                                element_list: list, text_context: str = None) -> dict:
    """
    Execute a specific runbook step with agent guidance.
    The runbook provides structure, the agent provides intelligence.
    """
    
    # Build runbook step instruction
    step_instruction = f"""
--- CURRENT RUNBOOK STEP ---
STEP: {runbook_step['name']}
ACTION: {runbook_step['action']}
DESCRIPTION: {runbook_step['description']}
TOOL TO USE: {runbook_step.get('tool', 'som_browser')}

EXPECTED FINDINGS TO LOG:
{chr(10).join(f"- {f}" for f in runbook_step.get('findings_to_log', []))}

TESTING SCENARIOS (if applicable):
{chr(10).join(f"- {s}" for s in runbook_step.get('test_scenarios', []))}

--- YOUR TASK ---
Execute this step intelligently. You must:
1. Use the specified tool/action
2. Log all expected findings
3. Adapt to what you observe
4. Report unexpected findings
"""
    
    # Inject RAG context (past learnings about this action)
    rag_context = ""
    if self.memory:
        rag_context = self.memory.retrieve_relevant_lessons(
            query=f"{runbook_step['action']} {runbook_step['name']}",
            action_type=runbook_step['action']
        )
    
    # Build full prompt
    prompt_parts = [
        f"CURRENT GOAL: {goal}",
        step_instruction,
        rag_context if rag_context else "",
        f"HISTORY (last 3 actions): {json.dumps(history[-3:])}",
        f"INTERACTIVE ELEMENTS:\n{self._format_elements(element_list)}",
        Part.from_data(screenshot_bytes, mime_type="image/jpeg")
    ]
    
    if text_context:
        prompt_parts.append(f"--- CONTEXT DATA ---\n{text_context}\n")
    
    prompt_parts.append("""
OUTPUT: JSON with the specific action to take, plus all findings from the runbook step.
{
    "thought": "Reasoning based on runbook step + observation",
    "action": "click" or "type" or "navigate" or "report_finding",
    "element_id": int or null,
    "value": string or null,
    "findings": {
        "finding_name": "finding_value",
        ...all expected findings from runbook step...
    }
}
""")
    
    # Generate response
    try:
        response = self.model.generate_content(
            prompt_parts,
            generation_config={"response_mime_type": "application/json"},
            safety_settings=self.safety
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"[Agent Brain Error] {e}")
        return {
            "thought": "Error in runbook step execution",
            "action": "wait",
            "findings": {}
        }
```

**Key Changes:**
1. **Structured Guidance:** Agent gets clear instructions from runbook
2. **Findings Schema:** Agent must populate `findings` dict matching runbook's `findings_to_log`
3. **Memory Integration:** RAG retrieves past learnings about this specific action
4. **Flexibility:** Agent can still adapt based on observations

**Acceptance Criteria:**
- [ ] Agent understands runbook step structure
- [ ] Agent populates findings dict correctly
- [ ] Agent can deviate when needed (with justification)
- [ ] Memory/RAG integration working
- [ ] Error handling preserves execution flow

---

### Task 3.2: Create Runbook Step Executor in AutonomousLoop

**File:** `core/autonomous_loop.py` (MODIFY)

Add method to execute runbook steps with the agent:

```python
async def _execute_runbook_step_with_agent(self, step: dict, runbook_context: dict) -> Dict[str, Any]:
    """
    Execute a single runbook step using the agent.
    Combines runbook structure with agent intelligence.
    """
    
    self.log_to_ui(f"[Runbook] 🎯 Step: {step['name']}")
    self.log_to_ui(f"[Runbook] 📋 Action: {step['action']}")
    
    # Get current page state
    triad = self.browser.get_snapshot_triad()
    elements = self.browser.get_interactive_elements()
    
    # Ask agent to execute step
    agent_decision = self.brain.plan_next_step_from_runbook(
        runbook_step=step,
        goal=runbook_context['mission_goal'],
        history=self.action_history,
        screenshot_bytes=triad['screenshot'],
        element_list=elements,
        text_context=triad.get('raw_source', '')
    )
    
    # Execute agent's action
    self._execute_agent_action(agent_decision)
    
    # Extract findings from agent response
    findings = agent_decision.get('findings', {})
    
    # Validate findings match expected schema
    expected_findings = step.get('findings_to_log', [])
    self._validate_findings(findings, expected_findings)
    
    return findings
```

**Acceptance Criteria:**
- [ ] Step execution integrates with agent
- [ ] Findings extracted and validated
- [ ] Actions executed correctly
- [ ] Screenshots captured at key points
- [ ] Errors handled gracefully

---

## Phase 4: Complete CTF Runbook

**Goal:** Create a production-ready CTF flag detection runbook

### Task 4.1: Implement ctf_runbook.yaml

**File:** `runbooks/ctf_runbook.yaml` (REPLACE)

```yaml
---
# CTF Flag Validation and Brainstorm Runbook
# Searches for CTF flags and triggers analysis if not found

metadata:
  name: "CTF Flag Validation"
  version: "1.0"
  description: "Detect CTF flags and trigger brainstorm if not found"
  author: "AI Hunter"
  
  prerequisites:
    optional: ["idor_runbook", "init_runbook"]
  
  triggers:
    - type: "playbook_complete"
      description: "End of CTF playbook, check for flag"
      confidence: 1.0
    
    - type: "manual"
      description: "User requests flag check"

steps:
  - id: "aggregate_mission_findings"
    name: "Aggregate All Mission Findings"
    action: "compile_findings"
    description: "Collect all findings from all previous runbooks"
    depends_on: []
    tool: "findings_aggregator"
    findings_to_log:
      - "Total findings count"
      - "Runbooks completed"
      - "All finding types"
  
  - id: "search_for_flag_patterns"
    name: "Search for FLAG Patterns"
    action: "pattern_search"
    description: "Search all findings for common CTF flag formats"
    depends_on: ["aggregate_mission_findings"]
    tool: "findings_aggregator"
    patterns:
      - "FLAG\\{[^}]+\\}"
      - "CTF\\{[^}]+\\}"
      - "flag\\{[^}]+\\}"
      - "\\b[A-Z0-9]{32,}\\b"  # Hash-like
      - "picoCTF\\{[^}]+\\}"
      - "CHTB\\{[^}]+\\}"
    findings_to_log:
      - "Flag found (Y/N)"
      - "Flag value"
      - "Flag format"
      - "Location (which finding/step)"
      - "Confidence (0.0-1.0)"
  
  - id: "validate_flag_format"
    name: "Validate Flag Format"
    action: "regex_validation"
    description: "Ensure found flag matches expected format"
    depends_on: ["search_for_flag_patterns"]
    tool: "validator"
    validation_rules:
      - "Not empty"
      - "Matches regex pattern"
      - "Not a false positive (e.g., code example)"
      - "Length is reasonable (5-200 chars)"
    findings_to_log:
      - "Valid flag (Y/N)"
      - "Validation errors (if any)"
      - "False positive indicators"
  
  - id: "report_flag_success"
    name: "Report Flag Discovery"
    action: "report_finding"
    description: "Log successful flag capture"
    depends_on: ["validate_flag_format"]
    condition: "flag_found"
    tool: "findings_repository"
    findings_to_log:
      - "Mission success: FLAG CAPTURED"
      - "Flag value"
      - "Discovery method"
      - "Time to flag (from mission start)"
  
  - id: "check_flag_not_found"
    name: "Check if Flag Not Found"
    action: "conditional_check"
    description: "Determine if we need to brainstorm"
    depends_on: ["validate_flag_format"]
    condition: "flag_not_found"
    findings_to_log:
      - "Flag not found in any findings"
      - "Total runbooks executed"
      - "Areas explored"
      - "Branching to brainstorm"

# Next runbooks based on flag status
next_runbooks:
  on_success:
    - runbook: "report_runbook"
      condition: "flag_found"
      priority: "high"
      description: "Generate success report with flag"
  
  on_failure:
    - runbook: "brainstorm_runbook"
      condition: "flag_not_found"
      priority: "high"
      description: "No flag found, analyze and recommend next steps"
  
  always:
    - runbook: "learn_runbook"
      priority: "low"
      description: "Learn from this mission regardless of outcome"

# Success criteria
success_criteria:
  - "All mission findings aggregated"
  - "Flag pattern search completed"
  - "Validation attempted (if flag found)"
  - "Next runbook determined based on flag status"

# Analysis
analysis:
  - id: "flag_analysis"
    name: "Analyze Flag Discovery"
    description: "If flag found, analyze how it was discovered"
    strategy:
      - "Which runbook led to flag?"
      - "What was the key action?"
      - "Can we replicate this pattern?"
      - "Was it expected or lucky?"
```

**Acceptance Criteria:**
- [ ] Searches all findings for flag patterns
- [ ] Validates flag format
- [ ] Branches to brainstorm_runbook if no flag
- [ ] Branches to report_runbook if flag found
- [ ] Logs discovery method for learning

---

## Phase 5: UI Integration

**Goal:** Add playbook selection and progress tracking to frontend

### Task 5.1: Backend API Endpoints

**File:** `backend/main.py` (MODIFY)

Add new endpoints:

```python
@app.get("/api/playbooks")
async def list_playbooks():
    """Get all available playbooks"""
    manager = PlaybookManager()
    playbooks = manager.list_available_playbooks()
    return {"playbooks": playbooks}

@app.get("/api/playbooks/{playbook_name}")
async def get_playbook_details(playbook_name: str):
    """Get detailed info about a playbook"""
    manager = PlaybookManager()
    playbook = manager.load_playbook(playbook_name)
    sequence = manager.get_runbook_sequence(playbook_name)
    return {
        "playbook": playbook,
        "sequence": sequence,
        "total_stages": len(sequence)
    }

@app.post("/api/missions/start-playbook")
async def start_playbook_mission(request: Request):
    """Start a mission with a playbook"""
    data = await request.json()
    
    # Create mission record
    mission_id = db.create_mission(
        goal=data['goal'],
        target_url=data['target_url'],
        instructions=data.get('instructions', ''),
        playbook_name=data['playbook_name']
    )
    
    # Start playbook execution
    loop = get_autonomous_loop()
    asyncio.create_task(
        loop.start_mission_with_playbook(
            playbook_name=data['playbook_name'],
            goal=data['goal'],
            target_url=data['target_url'],
            instructions=data.get('instructions', '')
        )
    )
    
    return {"mission_id": mission_id, "status": "started"}

@app.get("/api/missions/{mission_id}/playbook-progress")
async def get_playbook_progress(mission_id: int):
    """Get real-time playbook execution progress"""
    execution = db.get_playbook_execution(mission_id)
    return {
        "current_stage": execution['current_stage'],
        "total_stages": execution['total_stages'],
        "completed_stages": execution['completed_stages'],
        "current_runbook": execution['current_runbook'],
        "progress_percent": execution['progress_percent']
    }
```

**Acceptance Criteria:**
- [ ] Can list playbooks via API
- [ ] Can start mission with playbook
- [ ] Can get real-time progress
- [ ] Proper error handling

---

### Task 5.2: Frontend Playbook Selection UI

**File:** `frontend/public/js/missions.js` (MODIFY)

Add playbook selection to mission creation:

```javascript
// Load playbooks on page load
async function loadPlaybooks() {
    const response = await fetch('/api/playbooks');
    const data = await response.json();
    
    const selector = document.getElementById('playbook-selector');
    selector.innerHTML = `
        <option value="">-- No Playbook (Use Tactical Planner) --</option>
        ${data.playbooks.map(pb => `
            <option value="${pb.id}" 
                    data-category="${pb.category}"
                    data-difficulty="${pb.difficulty}">
                ${pb.name} (${pb.category} - ${pb.difficulty})
            </option>
        `).join('')}
    `;
}

// Show playbook details when selected
async function onPlaybookSelected(playbookName) {
    if (!playbookName) return;
    
    const response = await fetch(`/api/playbooks/${playbookName}`);
    const data = await response.json();
    
    // Show runbook sequence
    const sequenceHtml = data.sequence.map(rb => `
        <div class="runbook-step">
            <span class="stage">Stage ${rb.stage}</span>
            <span class="name">${rb.name}</span>
            ${rb.hitl_checkpoint ? '<span class="hitl">🚦 HITL</span>' : ''}
        </div>
    `).join('');
    
    document.getElementById('playbook-preview').innerHTML = `
        <h3>${data.playbook.metadata.name}</h3>
        <p>${data.playbook.metadata.description}</p>
        <div class="sequence">${sequenceHtml}</div>
    `;
}
```

**Acceptance Criteria:**
- [ ] Playbook dropdown populates
- [ ] Shows playbook preview on selection
- [ ] Can start mission with selected playbook
- [ ] Falls back to tactical planner if no playbook selected

---

### Task 5.3: Real-time Progress Visualization

**File:** `frontend/public/js/plan.js` (NEW)

```javascript
// Poll for playbook progress
function startProgressTracking(missionId) {
    const interval = setInterval(async () => {
        const response = await fetch(`/api/missions/${missionId}/playbook-progress`);
        const progress = await response.json();
        
        updateProgressBar(progress);
        updateCurrentRunbook(progress);
        
        if (progress.progress_percent >= 100) {
            clearInterval(interval);
        }
    }, 2000);
}

function updateProgressBar(progress) {
    const bar = document.getElementById('playbook-progress-bar');
    bar.style.width = `${progress.progress_percent}%`;
    bar.textContent = `Stage ${progress.current_stage} / ${progress.total_stages}`;
}

function updateCurrentRunbook(progress) {
    document.getElementById('current-runbook').innerHTML = `
        <div class="runbook-active">
            <span class="icon">⚙️</span>
            <span class="name">${progress.current_runbook}</span>
        </div>
    `;
}
```

**Acceptance Criteria:**
- [ ] Progress bar shows current stage
- [ ] Current runbook highlighted
- [ ] Updates in real-time
- [ ] Clean UI integration

---

## Phase 6: State Management Integration

**Goal:** Enable pause/resume and checkpointing

### Task 6.1: Checkpoint Creation in PlaybookExecutor

**File:** `core/playbook_executor.py` (MODIFY)

Add checkpointing after each runbook:

```python
async def _execute_runbook(self, runbook_name: str) -> Dict[str, Any]:
    """Execute a single runbook and return findings"""
    
    # ... execution logic ...
    
    # Create checkpoint after runbook completes
    await self._create_checkpoint(runbook_name, findings)
    
    return findings

async def _create_checkpoint(self, runbook_name: str, findings: Dict):
    """Create a state checkpoint for pause/resume"""
    
    checkpoint_data = {
        'playbook_name': self.current_playbook,
        'current_stage': self.manager.current_stage,
        'completed_stages': self.manager.completed_stages,
        'findings': findings,
        'browser_state': {
            'current_url': self.loop.browser.driver.current_url,
            'cookies': self.loop.browser.driver.get_cookies()
        },
        'timestamp': datetime.utcnow().isoformat()
    }
    
    await self.state_manager.checkpoint(
        mission_id=self.mission_id,
        name=f"after_{runbook_name}",
        full_state=checkpoint_data
    )
    
    self.loop.log_to_ui(f"[State] 💾 Checkpoint created: {runbook_name}")
```

**Acceptance Criteria:**
- [ ] Checkpoint created after each runbook
- [ ] Includes browser state
- [ ] Includes findings
- [ ] Stored in PostgreSQL

---

### Task 6.2: Pause/Resume Implementation

**File:** `core/playbook_executor.py` (MODIFY)

Add pause/resume methods:

```python
async def pause_execution(self):
    """Pause playbook execution"""
    self.paused = True
    await self._create_checkpoint("pause_point", {})
    self.loop.log_to_ui("[State] ⏸️ Execution paused")

async def resume_execution(self, mission_id: int, checkpoint_name: str = None):
    """Resume from checkpoint"""
    
    # Get latest checkpoint if not specified
    if not checkpoint_name:
        checkpoints = await self.state_manager.list_checkpoints(mission_id)
        checkpoint_name = checkpoints[-1]['name']
    
    # Restore state
    state = await self.state_manager.restore_checkpoint(mission_id, checkpoint_name)
    
    # Restore browser state
    self.loop.browser.driver.get(state['browser_state']['current_url'])
    for cookie in state['browser_state']['cookies']:
        self.loop.browser.driver.add_cookie(cookie)
    
    # Resume from current stage
    self.manager.current_playbook = state['playbook_name']
    self.manager.current_stage = state['current_stage']
    self.manager.completed_stages = state['completed_stages']
    
    self.loop.log_to_ui(f"[State] ▶️ Resumed from: {checkpoint_name}")
    
    # Continue execution
    await self._continue_execution()
```

**Acceptance Criteria:**
- [ ] Can pause mid-playbook
- [ ] Can resume from checkpoint
- [ ] Browser state restored
- [ ] Execution continues correctly

---

## Phase 7: Testing and Validation

### Task 7.1: Create Test Playbooks

**File:** `playbooks/test_simple_playbook.yaml` (NEW)

```yaml
---
metadata:
  name: "Simple Test Playbook"
  version: "1.0"
  description: "Basic playbook for testing execution flow"
  category: "test"

sequence:
  - runbook: "init_runbook"
    stage: 1
    name: "Initial Recon"
    required: true
    hitl_checkpoint: false
  
  - runbook: "brainstorm_runbook"
    stage: 2
    name: "Analysis"
    required: true
    hitl_checkpoint: true

configuration:
  max_requests_per_minute: 50
  timeout_per_runbook: 600
```

**File:** `playbooks/test_conditional_playbook.yaml` (NEW)

```yaml
---
metadata:
  name: "Conditional Branching Test"
  description: "Test conditional runbook insertion"

sequence:
  - runbook: "init_runbook"
    stage: 1
  
  - runbook: "idor_runbook"
    stage: 2

conditional_steps:
  - condition:
      type: "finding_match"
      pattern: "admin_access"
    then:
      insert_runbook: "memory_runbook"
      at_stage: 2.5
      description: "Admin found, search for similar cases"
```

**Acceptance Criteria:**
- [ ] Simple playbook executes end-to-end
- [ ] Conditional branching works
- [ ] HITL checkpoints trigger
- [ ] All findings logged

---

### Task 7.2: Integration Tests

**File:** `tests/test_playbook_integration.py` (NEW)

```python
import pytest
from core.playbook_executor import PlaybookExecutor
from core.autonomous_loop import AutonomousLoop

@pytest.mark.asyncio
async def test_simple_playbook_execution():
    """Test basic playbook execution"""
    # Setup
    loop = AutonomousLoop(tracker, repo, quota, db)
    executor = PlaybookExecutor(loop, db)
    
    # Execute
    result = await executor.execute_playbook(
        playbook_name="test_simple_playbook",
        goal="Test execution",
        target_url="http://localhost:8080",
        mission_id=1
    )
    
    # Assert
    assert result['status'] == 'completed'
    assert len(result['findings']) > 0
    assert result['stages_completed'] == 2

@pytest.mark.asyncio
async def test_conditional_branching():
    """Test conditional runbook insertion"""
    # ... test conditional logic ...

@pytest.mark.asyncio
async def test_pause_resume():
    """Test pause/resume functionality"""
    # ... test checkpointing ...
```

**Acceptance Criteria:**
- [ ] All integration tests pass
- [ ] Code coverage > 80%
- [ ] Edge cases handled

---

## Phase 8: Documentation and Migration

### Task 8.1: Create Playbook Guide

**File:** `docs/PLAYBOOKS.md` (NEW)

Comprehensive guide covering:
- What are playbooks/runbooks
- How to create a custom playbook
- YAML syntax reference
- Available actions and tools
- Conditional branching examples
- HITL checkpoint usage
- Best practices

### Task 8.2: Update QUICKSTART.md

**File:** `QUICKSTART.md` (MODIFY)

Add section on playbooks:

```markdown
## Using Playbooks

Playbooks provide structured, reproducible security testing workflows.

### Available Playbooks

- **CTF IDOR Testing**: Comprehensive IDOR vulnerability testing for CTF environments
- **Web Application Security Audit**: Full security assessment workflow
- **API Testing**: REST API security testing playbook

### Starting a Playbook Mission

1. Click **+ New Mission**
2. Select a playbook from the dropdown
3. Preview the runbook sequence
4. Enter target URL and goal
5. Click **Start Mission**

The agent will execute each runbook in sequence, pausing at HITL checkpoints for your approval.
```

### Task 8.3: Migration Guide

**File:** `docs/MIGRATION_TO_PLAYBOOKS.md` (NEW)

Guide for transitioning from tactical planner to playbooks:

- Feature comparison
- When to use playbooks vs tactical planner
- Migration path for existing missions
- Backward compatibility notes

---

## Implementation Timeline

**Estimated Effort:** 40-60 hours of development

| Phase | Tasks | Estimated Time | Priority |
|-------|-------|----------------|----------|
| Phase 1 | Core executor | 8-12 hours | **CRITICAL** |
| Phase 2 | Tool mapping | 6-8 hours | **HIGH** |
| Phase 3 | Agent integration | 8-10 hours | **HIGH** |
| Phase 4 | CTF runbook | 2-3 hours | **MEDIUM** |
| Phase 5 | UI integration | 6-8 hours | **HIGH** |
| Phase 6 | State management | 4-6 hours | **MEDIUM** |
| Phase 7 | Testing | 4-6 hours | **HIGH** |
| Phase 8 | Documentation | 2-4 hours | **MEDIUM** |

---

## Success Criteria

**Phase 1 Complete When:**
- [ ] PlaybookExecutor can execute a simple playbook end-to-end
- [ ] Runbooks execute in correct sequence order
- [ ] Findings aggregated across runbooks
- [ ] State persisted to database

**Phase 2 Complete When:**
- [ ] All browser/scanner/fuzzer actions mapped
- [ ] FindingsAggregator working
- [ ] ReportGenerator producing markdown

**Phase 3 Complete When:**
- [ ] Agent executes runbook steps correctly
- [ ] Findings schema populated by agent
- [ ] Memory/RAG integration working

**Phase 4 Complete When:**
- [ ] ctf_runbook.yaml fully implemented
- [ ] Flag detection working
- [ ] Conditional branching to brainstorm working

**Phase 5 Complete When:**
- [ ] Can select playbook from UI
- [ ] Real-time progress displayed
- [ ] Can start playbook mission

**Phase 6 Complete When:**
- [ ] Checkpoints created automatically
- [ ] Can pause/resume playbook execution
- [ ] Browser state restored correctly

**Phase 7 Complete When:**
- [ ] Integration tests passing
- [ ] Test playbooks working
- [ ] Code coverage > 80%

**Phase 8 Complete When:**
- [ ] PLAYBOOKS.md complete
- [ ] QUICKSTART.md updated
- [ ] Migration guide written

---

## Risk Mitigation

### Risk 1: Backward Compatibility

**Mitigation:** Keep `start_mission()` working alongside `start_mission_with_playbook()`. Frontend toggles between modes.

### Risk 2: Tool Action Mapping Complexity

**Mitigation:** Start with existing tools only. Stub missing tools with simple implementations. Expand gradually.

### Risk 3: Agent Not Following Runbook Structure

**Mitigation:** Strong prompt engineering + validation of agent output against runbook schema.

### Risk 4: Performance Degradation

**Mitigation:** Benchmark before/after. Use async execution. Cache findings aggregation.

---

## Rollback Plan

If implementation fails or causes critical issues:

1. **Revert Git Branch:** All changes are on a feature branch
2. **Database Migration Rollback:** `alembic downgrade -1`
3. **UI Toggle:** Frontend can disable playbook mode
4. **Keep Old System:** Tactical planner remains functional

---

## Next Steps

To begin implementation:

1. **Create Feature Branch:**
   ```bash
   git checkout -b feature/playbook-integration
   ```

2. **Start with Phase 1, Task 1.1:**
   - Create `core/playbook_executor.py`
   - Implement basic execution logic
   - Test with `test_simple_playbook.yaml`

3. **Commit Frequently:**
   - Small, atomic commits
   - Clear commit messages
   - Test after each commit

4. **Track Progress:**
   - Update todo list as you complete tasks
   - Document blockers and decisions

---

**Ready to begin implementation? Start with Phase 1, Task 1.1.**
