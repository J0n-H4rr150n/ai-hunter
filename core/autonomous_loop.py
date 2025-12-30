import time
from core.planner import Planner
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

    def start_mission(self, goal: str, target_url: str, instructions: str = None):
        """Bootstraps the mission and starts the loop."""
        print(f"\n[Auto] 🚀 Starting Autonomous Mission: {goal}")
        print(f"[Auto] 🎯 Target: {target_url}")
        
        if instructions:
            print(f"[Auto] 📋 User Instructions: {instructions}")
        
        # 1. Initialize browser (headless=False so you can see what it's doing)
        print("[Auto] 🌐 Launching browser...")
        self.browser = SoMBrowser(headless=False)
        self.tracker.set_browser(self.browser)
        
        # 2. Initialize Plan in Hive Bucket
        self.planner.set_mission(goal, target_url, instructions)
        
        try:
            # 3. Enter Loop
            self.run_loop()
        finally:
            # 4. Always cleanup browser
            print("[Auto] 🛑 Closing browser...")
            if self.browser:
                self.browser.close()
                self.browser = None
            self.tracker.set_browser(None)

    def run_loop(self):
        """Continuously executes tasks until the mission is done."""
        print("[Auto] Entering execution loop...")
        
        while True:
            # 1. Get Next Task
            task = self.planner.get_next_task()
            
            if not task:
                print("[Auto] ✅ No more pending tasks. Mission Complete.")
                break
                
            print(f"\n[Auto] ⚡ Picking up task: {task['description']} ({task['type']})")
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
                    print(f"[Auto] ⚠️ Unknown task type: {task['type']}")
                    self.planner.complete_task(task['id'], "Skipped: Unknown type")

            except Exception as e:
                print(f"[Auto] ❌ Task Failed: {e}")
                self.planner.fail_task(task['id'], str(e))
            
            # Short sleep to prevent CPU spinning if logic is instant
            time.sleep(1)

    def _execute_scan(self, task):
        url = task['target']
        print(f"[Auto] Running TechScanner on {url}...")
        
        # HTTP-based tech fingerprinting
        self.scanner.scan_url(url)
        
        # Browser-based visual reconnaissance
        if self.browser:
            print(f"[Auto] 🌐 Opening {url} in browser for visual analysis...")
            self.browser.navigate(url)
            
            # Capture visual snapshot with Set-of-Marks
            print("[Auto] 📸 Capturing page snapshot with interactive elements...")
            snapshot = self.browser.get_snapshot_triad()
            
            # Log the discovery
            self.tracker.capture_shadow("scan_complete", {
                "url": url,
                "num_elements": len(snapshot['elements'])
            })
            
            print(f"[Auto] ✓ Found {len(snapshot['elements'])} interactive elements on page")
            
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
        print(f"[Auto] Running Fuzzer on {url}...")
        
        # Get mission instructions for context
        mission = self.planner.get_mission()
        instructions = mission.get('instructions', '') if mission else ''
        
        # Parse instructions for fuzzing hints
        focus_on_ids = 'id' in instructions.lower()
        avoid_account_creation = 'create' in instructions.lower() and 'account' in instructions.lower()
        
        if instructions and instructions != "No specific instructions provided.":
            print(f"[Auto] 📋 Applying user guidance: {instructions[:80]}...")
        
        # Try traditional URL parameter fuzzing first
        self.fuzzer.fuzz_url_params(url)
        
        # If we have a browser, also fuzz discovered input fields
        if self.browser:
            print(f"[Auto] 🔍 Analyzing page for input fields to test...")
            
            # Get the current page snapshot
            snapshot = self.browser.get_snapshot_triad()
            
            # Find input elements
            input_elements = [e for e in snapshot['elements'] 
                            if e['tagName'] in ['input', 'textarea']]
            
            if input_elements:
                print(f"[Auto] Found {len(input_elements)} input fields to test")
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
                            print(f"[Auto] ⏭️  Skipping account field (per instructions): {elem_text[:30]}")
                            continue
                    
                    print(f"[Auto] Testing input element #{elem_id}: {elem_text[:30]}")
                    
                    # Adjust payloads based on instructions
                    if focus_on_ids and ('id' in elem_text or 'id' in elem_type):
                        # Use ID-focused payloads
                        test_payloads = ["1", "999999", "-1", "0", "admin", "1 OR 1=1"]
                        print(f"[Auto] 🎯 Using ID-focused payloads (per instructions)")
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
                            print(f"[Auto] Failed to test element {elem_id}: {e}")
            else:
                print("[Auto] No input fields found on page")
        
        # Check if we found critical errors (500s)
        crashes = self.repo.search_findings(tag="500", finding_type="vulnerability_crash")
        if crashes:
            print(f"[Auto] 🚨 Fuzzer found {len(crashes)} crashes! Adding triage task.")
            self.planner.add_task("manual_review", url, "Human review required for confirmed crashes")

        self.planner.complete_task(task['id'], "Fuzzing completed")

    def _execute_analysis(self, task):
        print("[Auto] analyzing findings...")
        # Simple summary of what's in the hive
        all_findings = self.repo.search_findings()
        summary = f"Total findings: {len(all_findings)}"
        print(f"[Auto] Analysis: {summary}")
        self.planner.complete_task(task['id'], summary)