import time
from core.planner import Planner
from core.workflow import MissionWorkflow, WorkflowState
from core.human_interface import HumanInterface
from agents.planner import TacticalPlanner
from tools.tech_scanner import TechScanner
from tools.fuzzer import Fuzzer
from tools.som_browser import SoMBrowser
from memory.finding_repository import FindingRepository
from core.agent_tracker import AgentTracker
from core.quota_manager import QuotaManager

class AutonomousLoop:
    """
    The main execution loop for the autonomous agent.
    Polls the Planner for tasks and delegates them to the appropriate Tools.
    """

    def __init__(self, tracker: AgentTracker, repo: FindingRepository, quota: QuotaManager):
        self.tracker = tracker
        self.repo = repo
        self.quota = quota
        
        # Tools
        self.scanner = TechScanner(repo, quota)
        self.fuzzer = Fuzzer(repo, quota)
        self.planner = Planner()
        
        # Browser (will be initialized per mission)
        self.browser = None
        
        # UI integration
        self.mission_id = None
        self.ui_callback = None
        
    def log_to_ui(self, message: str):
        \"\"\"Send log message to UI if callback is set\"\"\"
        if self.ui_callback:
            self.ui_callback(message)
        print(message)  # Always print to console too

    def start_mission(self, goal: str, target_url: str, instructions: str = None):
        """Bootstraps the mission and starts the loop with LLM-generated plan and human approval."""
        
        self.log_to_ui(f"\n[Auto] 🚀 Starting Autonomous Mission: {goal}")
        self.log_to_ui(f"[Auto] 🎯 Target: {target_url}")
        
        if instructions:
            self.log_to_ui(f"[Auto] 📋 User Instructions: {instructions}")
        
        # 1. Initialize workflow
        workflow = MissionWorkflow(goal, target_url, instructions)
        workflow.state = WorkflowState.PLANNING
        
        # 2. Initialize browser (headless mode for Docker)
        self.log_to_ui("[Auto] 🌐 Launching browser...")
        self.browser = SoMBrowser(headless=True)
        self.tracker.set_browser(self.browser)
        
        # 3. Generate Plan using Gemini
        self.log_to_ui("[Auto] 🧠 Generating execution plan with Gemini 2.5 Pro...")
        try:
            # Quick tech scan first
            tech_report = self._quick_tech_scan(target_url)
            
            # Navigate to get visual context
            self.browser.navigate(target_url)
            triad = self.browser.get_snapshot_triad()
            
            # Generate plan with LLM
            tactical_planner = TacticalPlanner()
            self.log_to_ui("[Planner] Synthesizing Tech Stack & Visuals into Plan...")
            plan = tactical_planner.generate_plan(goal, triad, tech_report)
            workflow.set_plan(plan)
            
        except Exception as e:
            self.log_to_ui(f"[Auto] ❌ Plan generation failed: {e}")
            self.log_to_ui("[Auto] 🛑 Aborting mission")
            if self.browser:
                self.browser.close()
                self.browser = None
            self.tracker.set_browser(None)
            return
        
        # 4. INTERRUPT: Human Approval Gate
        self.log_to_ui("\n[Auto] ⏸️  PAUSING for human approval...")
        
        # Check if we have a web approval callback (injected by backend)
        if hasattr(self, 'web_approval_callback') and self.web_approval_callback:
            # The callback should be a synchronous wrapper that handles the async call
            approved, edited_plan = self.web_approval_callback(plan)
        else:
            # Fall back to terminal-based approval
            interface = HumanInterface(self.tracker)
            approved, edited_plan = interface.approve_plan(plan)
        
        if not approved:
            self.log_to_ui("[Auto] 🛑 Mission aborted by human")
            workflow.reject()
            if self.browser:
                self.browser.close()
                self.browser = None
            self.tracker.set_browser(None)
            return
        
        # 5. Apply approved/edited plan
        workflow.approve(edited_plan)
        self.planner.set_mission(goal, target_url, instructions)
        
        # Override with the approved plan's budgets
        if edited_plan.get('budgets'):
            for tool_name, limit in edited_plan['budgets'].items():
                self.quota.set_limit(tool_name, limit)
        
        try:
            # 6. Enter Loop
            self.run_loop()
            workflow.complete()
        finally:
            # 7. Always cleanup browser
            self.log_to_ui("[Auto] 🛑 Closing browser...")
            if self.browser:
                self.browser.close()
                self.browser = None
            self.tracker.set_browser(None)
    
    def _quick_tech_scan(self, url: str) -> dict:
        """Quick tech scan without full fingerprinting"""
        import requests
        try:
            resp = requests.get(url, timeout=5)
            return {
                "server": resp.headers.get("Server", "Unknown"),
                "framework": [],
                "lang": "Unknown",
                "interesting_headers": {k: v for k, v in resp.headers.items() 
                                       if k.lower() in ["x-powered-by", "x-aspnet-version", "x-generator"]},
                "findings": []
            }
        except Exception as e:
            self.log_to_ui(f"[Auto] Tech scan warning: {e}")
            return {
                "server": "Unknown",
                "framework": [],
                "lang": "Unknown",
                "interesting_headers": {},
                "findings": []
            }

    def run_loop(self):
        """Continuously executes tasks until the mission is done."""
        self.log_to_ui("[Auto] Entering execution loop...")
        
        while True:
            # 1. Get Next Task
            task = self.planner.get_next_task()
            
            if not task:
                self.log_to_ui("[Auto] ✅ No more pending tasks. Mission Complete.")
                break
            
            self.log_to_ui(f"\n[Auto] ⚡ Picking up task: {task['description']} ({task['type']})")
            self.planner.start_task(task['id'])
            
            # Capture Shadow (Visual log of starting the task)
            self.tracker.capture_shadow(f"start_{task['type']}", {"task_id": task['id']})

            # 2. Execute Logic
            try:
                if task['type'] == 'scan':
                    self._execute_scan(task)
                elif task['type'] == 'fuzz':
                    self._execute_fuzz(task)
                elif task['type'] == 'analyze':
                    self._execute_analysis(task)
                else:
                    self.log_to_ui(f"[Auto] ⚠️ Unknown task type: {task['type']}")
                    self.planner.complete_task(task['id'], "Skipped: Unknown type")

            except Exception as e:
                self.log_to_ui(f"[Auto] ❌ Task Failed: {e}")
                self.planner.fail_task(task['id'], str(e))
            
            # Short sleep to prevent CPU spinning if logic is instant
            time.sleep(1)

    def _execute_scan(self, task):
        url = task['target']
        self.log_to_ui(f"[Auto] Running TechScanner on {url}...")
        self.log_to_ui(f"[Scanner] Analyzing technology stack for: {url}")
        
        # HTTP-based tech fingerprinting
        self.scanner.scan_url(url)
        
        # Browser-based visual reconnaissance
        if self.browser:
            self.log_to_ui(f"[Auto] 🌐 Opening {url} in browser for visual analysis...")
            self.browser.navigate(url)
            
            # Capture visual snapshot with Set-of-Marks
            self.log_to_ui("[Auto] 📸 Capturing page snapshot with interactive elements...")
            snapshot = self.browser.get_snapshot_triad()
            
            # Log the discovery
            self.tracker.capture_shadow("scan_complete", {
                "url": url,
                "num_elements": len(snapshot['elements'])
            })
            
            self.log_to_ui(f"[Auto] ✓ Found {len(snapshot['elements'])} interactive elements on page")
            
            # Save interesting findings to memory
            if snapshot['elements']:
                self.repo.save_finding(
                    content={
                        "url": url,
                        "interactive_elements": snapshot['elements'][:10]  # First 10
                    },
                    finding_type="page_discovery",
                    source="AutonomousScanner",
                    tags=["recon", "page_mapping"]
                )
        
        self.planner.complete_task(task['id'], "Scan completed")

    def _execute_fuzz(self, task):
        url = task['target']
        self.log_to_ui(f"[Auto] Running Fuzzer on {url}...")
        
        # Get mission instructions for context
        mission = self.planner.get_mission()
        instructions = mission.get('instructions', '') if mission else ''
        
        # Parse instructions for fuzzing hints
        focus_on_ids = 'id' in instructions.lower()
        avoid_account_creation = 'create' in instructions.lower() and 'account' in instructions.lower()
        
        if instructions and instructions != "No specific instructions provided.":
            self.log_to_ui(f"[Auto] 📋 Applying user guidance: {instructions[:80]}...")
        
        # Try traditional URL parameter fuzzing first
        self.fuzzer.fuzz_url_params(url)
        
        # If we have a browser, also fuzz discovered input fields
        if self.browser:
            self.log_to_ui(f"[Auto] 🔍 Analyzing page for input fields to test...")
            
            # Get the current page snapshot
            snapshot = self.browser.get_snapshot_triad()
            
            # Find input elements
            input_elements = [e for e in snapshot['elements'] 
                            if e['tagName'] in ['input', 'textarea']]
            
            if input_elements:
                self.log_to_ui(f"[Auto] Found {len(input_elements)} input fields to test")
                self.tracker.capture_shadow("fuzz_inputs_discovered", {
                    "url": url,
                    "inputs": len(input_elements)
                })
                
                # Test first few inputs with payloads
                for i, elem in enumerate(input_elements[:5]):  # Limit to first 5
                    elem_id = elem['id']
                    elem_text = elem.get('text', '').lower()
                    elem_type = elem.get('type', '').lower()
                    
                    # Skip account creation fields if instructed
                    if avoid_account_creation:
                        skip_keywords = ['username', 'email', 'password', 'register', 'signup']
                        if any(kw in elem_text for kw in skip_keywords):
                            self.log_to_ui(f"[Auto] ⏭️  Skipping account field (per instructions): {elem_text[:30]}")
                            continue
                    
                    self.log_to_ui(f"[Auto] Testing input element #{elem_id}: {elem_text[:30]}")
                    
                    # Adjust payloads based on instructions
                    if focus_on_ids and ('id' in elem_text or 'id' in elem_type):
                        # Use ID-focused payloads
                        test_payloads = ["1", "999999", "-1", "0", "admin", "1 OR 1=1"]
                        self.log_to_ui(f"[Auto] 🎯 Using ID-focused payloads (per instructions)")
                    else:
                        # Standard security payloads
                        test_payloads = ["<script>alert(1)</script>", "' OR '1'='1", "../../etc/passwd"]
                    
                    for payload in test_payloads:
                        if not self.quota.check_limit("actions"):
                            break
                            
                        try:
                            # Type the payload
                            self.browser.interact("type", elem_id, payload)
                            self.quota.tally("actions", 1)
                            
                            # Capture the result
                            self.tracker.capture_shadow(f"fuzz_input_{elem_id}", {
                                "payload": payload[:50],
                                "element": elem_id
                            })
                            
                        except Exception as e:
                            self.log_to_ui(f"[Auto] Failed to test element {elem_id}: {e}")
            else:
                self.log_to_ui("[Auto] No input fields found on page")
        
        # Check if we found critical errors (500s)
        crashes = self.repo.search_findings(tag="500", finding_type="vulnerability_crash")
        if crashes:
            self.log_to_ui(f"[Auto] 🚨 Fuzzer found {len(crashes)} crashes! Adding triage task.")
            self.planner.add_task("manual_review", url, "Human review required for confirmed crashes")

        self.planner.complete_task(task['id'], "Fuzzing completed")

    def _execute_analysis(self, task):
        self.log_to_ui("[Auto] analyzing findings...")
        # Simple summary of what's in the hive
        all_findings = self.repo.search_findings()
        summary = f"Total findings: {len(all_findings)}"
        self.log_to_ui(f"[Auto] Analysis: {summary}")
        self.planner.complete_task(task['id'], summary)