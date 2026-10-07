import time
import asyncio
from core.planner import Planner
from core.workflow import MissionWorkflow, WorkflowState
from core.human_interface import HumanInterface
from agents.planner import TacticalPlanner
from tools.tech_scanner import TechScanner
from tools.fuzzer import Fuzzer
from tools.som_browser import SoMBrowser
from core.browser_thread import ThreadedBrowser
from core.mission_control import MissionControl, MissionStopped
from memory.finding_repository import FindingRepository
from core.agent_tracker import AgentTracker
from config.config import Config
from core.quota_manager import QuotaManager
from core.playbook_executor import PlaybookExecutor, PlaybookExecutionError

class AutonomousLoop:
    """
    The main execution loop for the autonomous agent.
    Polls the Planner for tasks and delegates them to the appropriate Tools.
    """

    def __init__(self, tracker: AgentTracker, repo: FindingRepository, quota: QuotaManager, db=None):
        self.tracker = tracker
        self.repo = repo
        self.quota = quota
        self.db = db  # Database for iteration management
        
        # Tools
        self.scanner = TechScanner(repo, quota)
        self.fuzzer = Fuzzer(repo, quota)
        self.planner = Planner()
        
        # Browser (will be initialized per mission)
        self.browser = None

        # Pause/stop signalling. The backend flips these; every checkpoint below
        # observes them, so a stop cannot be swallowed by a long-running phase.
        self.control = MissionControl()
        
        # UI integration
        self.mission_id = None
        self.ui_callback = None
        self.web_approval_callback = None  # For plan approval
        self.tool_approval_callback = None  # For HITL tool approval
        self.hitl_enabled = False  # HITL flag
        
    def log_to_ui(self, message: str, screenshot: dict = None):
        """Send log message to UI if callback is set"""
        if self.ui_callback:
            self.ui_callback(message, screenshot)
        else:
            print(message)  # Fallback to console
    
    def _send_screenshot_to_ui(self, message: str, shadow_result: dict):
        """Send a screenshot to the UI via callback."""
        if self.ui_callback and shadow_result:
            print(f"[DEBUG] Sending screenshot to UI: {shadow_result.get('relative_path')}")
            
            # Instead of base64, send the path to fetch via API
            # Path format: screenshots/2025-12-30/mission_17/18-17-16-271_scan_complete.png
            relative_path = shadow_result["relative_path"]
            parts = relative_path.replace("\\", "/").split("/")
            
            if len(parts) >= 4:  # screenshots/date/mission/file.png
                date = parts[1]
                mission_id = parts[2]
                filename = parts[3]
                api_url = f"/api/screenshots/{date}/{mission_id}/{filename}"
                
                screenshot_data = {
                    "url": api_url,
                    "path": relative_path
                }
                print(f"[DEBUG] Screenshot API URL: {api_url}")
                self.log_to_ui(message, screenshot=screenshot_data)
            else:
                print(f"[DEBUG] Invalid path format: {relative_path}")
                self.log_to_ui(message)
        else:
            print(f"[DEBUG] Screenshot NOT sent - callback: {self.ui_callback is not None}, shadow_result: {shadow_result is not None}")
            # Fallback to regular log
            self.log_to_ui(message)
    
    def _request_tool_approval(self, tool_name: str, tool_inputs: dict, context: dict) -> dict:
        """Request human approval for a tool call via HITL."""
        if not self.tool_approval_callback:
            # No callback means no HITL, auto-approve
            print(f"[HITL] No approval callback set, auto-approving {tool_name}")
            return {'approved': True, 'edited_inputs': tool_inputs, 'feedback': None}
        
        if not self.hitl_enabled:
            # HITL disabled, auto-approve
            print(f"[HITL] HITL disabled, auto-approving {tool_name}")
            return {'approved': True, 'edited_inputs': tool_inputs, 'feedback': None}
        
        # Call the approval callback (will block until human responds)
        print(f"[HITL] Requesting approval for {tool_name}, blocking until response...")
        self.log_to_ui(f"[Auto] ⏸️ Requesting approval for: {tool_name}")
        
        approval_response = self.tool_approval_callback(tool_name, tool_inputs, context)
        print(f"[HITL] Received approval response: {approval_response}")
        
        if approval_response.get('approved'):
            if approval_response.get('edited_inputs'):
                self.log_to_ui(f"[Auto] ✅ Approved with edits: {tool_name}")
            else:
                self.log_to_ui(f"[Auto] ✅ Approved: {tool_name}")
        else:
            self.log_to_ui(f"[Auto] ❌ Rejected: {tool_name}")
            if approval_response.get('feedback'):
                self.log_to_ui(f"[Auto] 💬 Feedback: {approval_response['feedback']}")
        
        return approval_response

    async def start_mission(self, goal: str, target_url: str, instructions: str = None):
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
        loop = asyncio.get_event_loop()
        self.browser = await loop.run_in_executor(
            None, lambda: ThreadedBrowser(lambda: SoMBrowser(headless=True))
        )
        self.tracker.set_browser(self.browser)
        
        # 3. Generate Plan using the local model
        self.log_to_ui(f"[Auto] 🧠 Generating execution plan with {Config.LLM_MODEL}...")
        try:
            # Scanning, navigating and the planning call are all blocking, and the
            # model call alone can run for tens of seconds. Keep them off the event
            # loop so /stop, /pause and the rest of the API stay responsive while the
            # plan is being produced.
            def _build_plan():
                tech_report = self._quick_tech_scan(target_url)

                # Navigate to get visual context
                self.browser.navigate(target_url)
                triad = self.browser.get_snapshot_triad()

                # Generate plan with LLM
                tactical_planner = TacticalPlanner()
                self.log_to_ui("[Planner] Synthesizing Tech Stack & Visuals into Plan...")
                return tactical_planner.generate_plan(goal, triad, tech_report)

            plan = await loop.run_in_executor(None, _build_plan)
            self.control.raise_if_stopped()
            workflow.set_plan(plan)

        except MissionStopped:
            self.log_to_ui("[Auto] ⏹️ Mission stopped during planning.")
            if self.browser:
                self.browser = None
            self.tracker.set_browser(None)
            return
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
            # The backend's wrapper blocks on run_coroutine_threadsafe(...).result().
            # Calling it inline would park the event loop waiting on a coroutine that
            # only that same loop can run — a permanent deadlock. Run it on a worker
            # thread so the loop stays free to service the approval request.
            approved, edited_plan = await loop.run_in_executor(
                None, self.web_approval_callback, plan
            )
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
        
        # 5. Apply approved/edited plan and create Iteration 1
        workflow.approve(edited_plan)
        self.planner.set_mission(goal, target_url, instructions)
        
        # Override with the approved plan's budgets
        if edited_plan.get('budgets'):
            for tool_name, limit in edited_plan['budgets'].items():
                self.quota.set_limit(tool_name, limit)
        
        # Create Iteration 1 if database is available
        iteration_id = None
        if self.db and self.mission_id:
            try:
                iteration_id = await self.db.create_iteration(
                    mission_id=self.mission_id,
                    iteration_number=1,
                    plan=edited_plan
                )
                self.log_to_ui(f"[Auto] ✅ Created Iteration 1 (ID: {iteration_id})")
                
                # Update iteration status to in_progress
                await self.db.update_iteration_status(iteration_id, "in_progress")
            except Exception as e:
                self.log_to_ui(f"[Auto] ⚠️ Could not create iteration in DB: {e}")
        
        try:
            # 6. Run Iteration 1
            if iteration_id:
                await self.run_iteration(iteration_id, edited_plan)
            else:
                # Fallback to old behavior if no DB
                await asyncio.get_event_loop().run_in_executor(None, self.run_loop)
            
            workflow.complete()
        except MissionStopped:
            self.log_to_ui("[Auto] ⏹️ Mission stopped by user.")
        finally:
            # 7. Always cleanup browser
            self.log_to_ui("[Auto] 🛑 Closing browser...")
            if self.browser:
                self.browser.close()
                self.browser = None
            self.tracker.set_browser(None)
    
    async def start_mission_with_playbook(self, playbook_name: str, goal: str, 
                                         target_url: str, instructions: str = None):
        """
        New execution path using playbook/runbook system.
        Co-exists with old tactical planner for backward compatibility.
        
        Args:
            playbook_name: Name of playbook YAML file (without .yaml extension)
            goal: Mission objective
            target_url: Target URL to test
            instructions: Optional user instructions
        
        Returns:
            Execution summary dict
        """
        
        self.log_to_ui(f"\n[Playbook] 🎯 Starting Playbook Mission: {playbook_name}")
        self.log_to_ui(f"[Playbook] 🚀 Goal: {goal}")
        self.log_to_ui(f"[Playbook] 🌐 Target: {target_url}")
        
        if instructions:
            self.log_to_ui(f"[Playbook] 📋 User Instructions: {instructions}")
        
        # Initialize browser (headless mode for Docker)
        self.log_to_ui("[Playbook] 🌐 Launching browser...")
        loop = asyncio.get_event_loop()
        self.browser = await loop.run_in_executor(
            None, lambda: ThreadedBrowser(lambda: SoMBrowser(headless=True))
        )
        self.tracker.set_browser(self.browser)
        
        # Initialize playbook executor
        playbook_executor = PlaybookExecutor(self, self.db)
        
        try:
            # Execute playbook
            result = await playbook_executor.execute_playbook(
                playbook_name=playbook_name,
                goal=goal,
                target_url=target_url,
                mission_id=self.mission_id,
                instructions=instructions,
                skip_validation=False  # Always validate for safety
            )
            
            # Log summary
            self.log_to_ui(f"\n[Playbook] ✅ Playbook execution complete!")
            self.log_to_ui(f"[Playbook] 📊 Status: {result['status']}")
            self.log_to_ui(f"[Playbook] 📊 Runbooks completed: {len(result['completed_runbooks'])}")
            self.log_to_ui(f"[Playbook] 📊 Total findings: {result['total_findings']}")
            
            if result['failed_runbooks']:
                self.log_to_ui(f"[Playbook] ⚠️  Failed runbooks: {len(result['failed_runbooks'])}")
            
            return result
            
        except PlaybookExecutionError as e:
            self.log_to_ui(f"[Playbook] ❌ Playbook execution failed: {e}")
            raise
        
        finally:
            # Always cleanup browser
            self.log_to_ui("[Playbook] 🛑 Closing browser...")
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
            # Honour pause/stop before committing to another task.
            self.control.checkpoint(
                on_pause=lambda: self.log_to_ui("[Auto] ⏸️ Paused — waiting for resume..."),
                on_resume=lambda: self.log_to_ui("[Auto] ▶️ Resumed."),
            )

            # 1. Get Next Task
            task = self.planner.get_next_task()
            
            if not task:
                self.log_to_ui("[Auto] ✅ No more pending tasks. Mission Complete.")
                break
            
            self.log_to_ui(f"\n[Auto] ⚡ Picking up task: {task['description']} ({task['type']})")
            self.planner.start_task(task['id'])
            
            # Capture Shadow (Visual log of starting the task)
            shadow_result = self.tracker.capture_shadow(f"start_{task['type']}", {"task_id": task['id']})
            if shadow_result:
                self._send_screenshot_to_ui(f"Starting task: {task['description']}", shadow_result)

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
        
        # Request approval for scan operation
        approval = self._request_tool_approval(
            tool_name='scan',
            tool_inputs={'url': url, 'task_id': task['id']},
            context={'task_type': 'scan', 'description': task.get('description', '')}
        )
        
        if not approval.get('approved'):
            self.log_to_ui(f"[Auto] ⏭️ Scan rejected, skipping task")
            self.planner.complete_task(task['id'], "Skipped: User rejected")
            return
        
        # Use edited inputs if provided
        if approval.get('edited_inputs'):
            url = approval['edited_inputs'].get('url', url)
        
        self.log_to_ui(f"[Auto] Running TechScanner on {url}...")
        self.log_to_ui(f"[Scanner] Analyzing technology stack for: {url}")
        
        # HTTP-based tech fingerprinting
        tech_results = self.scanner.scan_url(url)
        
        # Show detailed tech stack results
        if tech_results:
            tech_html = "<details open><summary>🔍 <b>Technology Stack Identified</b></summary><div style='padding-left: 1rem; margin-top: 0.5rem;'>"
            for category, value in tech_results.items():
                tech_html += f"<div>• <b>{category}</b>: {value}</div>"
            tech_html += "</div></details>"
            self.log_to_ui(tech_html)
        else:
            self.log_to_ui("[Scanner] ℹ️ No specific technologies identified.")
        
        # Browser-based visual reconnaissance
        if self.browser:
            self.control.checkpoint()
            self.log_to_ui(f"[Auto] 🌐 Opening {url} in browser for visual analysis...")
            self.browser.navigate(url)
            
            # Capture visual snapshot with Set-of-Marks
            self.log_to_ui("[Auto] 📸 Capturing page snapshot with interactive elements...")
            snapshot = self.browser.get_snapshot_triad()
            
            # Always capture screenshot regardless
            shadow_result = self.tracker.capture_shadow("scan_complete", {
                "url": url,
                "num_elements": len(snapshot['elements'])
            })
            
            message = f"[Auto] ✓ Found {len(snapshot['elements'])} interactive elements on page"
            if shadow_result:
                self._send_screenshot_to_ui(message, shadow_result)
            else:
                self.log_to_ui(message)
                self.log_to_ui("[Debug] No screenshot captured - browser might not be ready")
            
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
        
        # Request approval for fuzz operation
        approval = self._request_tool_approval(
            tool_name='fuzz',
            tool_inputs={'url': url, 'task_id': task['id']},
            context={'task_type': 'fuzz', 'description': task.get('description', '')}
        )
        
        if not approval.get('approved'):
            self.log_to_ui(f"[Auto] ⏭️ Fuzzing rejected, skipping task")
            self.planner.complete_task(task['id'], "Skipped: User rejected")
            return
        
        # Use edited inputs if provided
        if approval.get('edited_inputs'):
            url = approval['edited_inputs'].get('url', url)
        
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
                shadow_result = self.tracker.capture_shadow("fuzz_inputs_discovered", {
                    "url": url,
                    "inputs": len(input_elements)
                })
                if shadow_result:
                    self._send_screenshot_to_ui(f"[Auto] Discovered {len(input_elements)} testable inputs", shadow_result)
                
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
                        self.control.checkpoint()
                        if not self.quota.check_limit("actions"):
                            break
                        
                        # Request approval for each payload test if HITL enabled
                        payload_approval = self._request_tool_approval(
                            tool_name='type',
                            tool_inputs={'element_id': elem_id, 'payload': payload, 'element_text': elem_text[:50]},
                            context={'fuzzing': True, 'url': url, 'payload_type': 'xss' if '<script>' in payload else 'sqli' if 'OR' in payload else 'generic'}
                        )
                        
                        if not payload_approval.get('approved'):
                            self.log_to_ui(f"[Auto] ⏭️ Payload test rejected: {payload[:30]}")
                            continue
                        
                        # Use edited payload if provided
                        actual_payload = payload_approval.get('edited_inputs', {}).get('payload', payload) if payload_approval.get('edited_inputs') else payload
                            
                        try:
                            # Clear network logs to isolate this request
                            self.browser.clear_network_logs()
                            
                            # Type the actual (possibly edited) payload
                            self.browser.interact("type", elem_id, actual_payload)
                            self.quota.tally("actions", 1)
                            
                            # Try to submit the form
                            submit_btn_id = self.browser.find_submit_button()
                            response_data = None
                            
                            if submit_btn_id:
                                self.log_to_ui(f"[Auto] 📤 Submitting form with payload...")
                                self.browser.interact("click", submit_btn_id)
                                self.quota.tally("actions", 1)
                                
                                # Wait for network response
                                time.sleep(1)
                                
                                # Capture the request/response
                                response_data = self.browser.get_last_request_response()
                                
                                # Analyze the response
                                analysis = self._analyze_fuzz_response(payload, response_data, self.browser.page)
                                
                                # Save Burp-style request/response
                                shadow_result = self.tracker.capture_shadow(f"fuzz_test_{elem_id}", {
                                    "payload": payload,
                                    "element": elem_id,
                                    "submitted": True,
                                    "request": {
                                        "method": response_data.get("method") if response_data else "N/A",
                                        "url": response_data.get("url") if response_data else "N/A",
                                    },
                                    "response": {
                                        "status": response_data.get("status") if response_data else "N/A",
                                        "body": response_data.get("body") if response_data else "N/A",
                                    },
                                    "analysis": analysis
                                })
                                if shadow_result:
                                    self._send_screenshot_to_ui(f"[Auto] 🧪 Tested payload: {payload[:30]}...", shadow_result)
                                
                                # Log interesting findings
                                if analysis.get("reflected"):
                                    self.log_to_ui(f"[Auto] 🚨 Payload REFLECTED in response - potential XSS!")
                                    self.repo.save_finding(
                                        content={"url": url, "payload": payload, "element": elem_id, "type": "reflected_input"},
                                        finding_type="xss_potential",
                                        source="FuzzerTool",
                                        tags=["xss", "reflected", "high_priority"]
                                    )
                                
                                if analysis.get("error_detected"):
                                    self.log_to_ui(f"[Auto] 💥 Error detected: {analysis['error_message'][:100]}")
                                    self.repo.save_finding(
                                        content={"url": url, "payload": payload, "error": analysis["error_message"]},
                                        finding_type="error_disclosure",
                                        source="FuzzerTool",
                                        tags=["error", "info_disclosure"]
                                    )
                                
                                # Navigate back to test next payload
                                self.browser.page.go_back()
                                time.sleep(0.5)
                            else:
                                # No submit button found, just capture the filled form
                                self.tracker.capture_shadow(f"fuzz_input_{elem_id}", {
                                    "payload": payload[:50],
                                    "element": elem_id,
                                    "submitted": False,
                                    "note": "No submit button found"
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
    
    def _analyze_fuzz_response(self, payload, response_data, page):
        """Analyze a fuzzing response for vulnerabilities."""
        analysis = {
            "reflected": False,
            "error_detected": False,
            "error_message": None,
            "timing_anomaly": False
        }
        
        if not response_data:
            return analysis
        
        # Get page content
        try:
            page_content = page.content()
            visible_text = page.inner_text('body')
        except:
            page_content = ""
            visible_text = ""
        
        # Check for payload reflection (XSS)
        if payload in page_content or payload in visible_text:
            analysis["reflected"] = True
        
        # Check for common error patterns
        error_patterns = [
            "SQL syntax", "mysql_", "ORA-", "PostgreSQL",
            "syntax error", "unexpected token",
            "Traceback", "Exception", "Error:",
            "stack trace", "at line",
            "Warning:", "Fatal error",
            "undefined index", "undefined variable"
        ]
        
        combined_text = (page_content + visible_text).lower()
        for pattern in error_patterns:
            if pattern.lower() in combined_text:
                analysis["error_detected"] = True
                # Extract error message snippet
                try:
                    idx = combined_text.index(pattern.lower())
                    analysis["error_message"] = combined_text[max(0, idx-50):idx+200]
                except:
                    analysis["error_message"] = f"Pattern '{pattern}' detected"
                break
        
        # Check response status
        if response_data.get("status", 200) >= 500:
            analysis["error_detected"] = True
            analysis["error_message"] = f"Server error: {response_data.get('status')}"
        
        return analysis

    def _execute_analysis(self, task):
        self.log_to_ui("[Auto] analyzing findings...")
        # Get all findings from the hive
        all_findings = self.repo.search_findings()
        
        # Categorize findings
        by_type = {}
        critical_vulns = []
        for finding in all_findings:
            ftype = finding.get('type', 'unknown')  # Use 'type' not 'finding_type'
            by_type[ftype] = by_type.get(ftype, 0) + 1
            
            # Check for critical vulnerabilities
            if finding.get('severity') in ['critical', 'high'] or \
               ftype in ['xss_potential', 'error_disclosure', 'vulnerability', 'injection', 'xss', 'sqli', 'rce']:
                critical_vulns.append(finding)
        
        # Build complete HTML as single message
        analysis_html = f"<details open><summary>📊 <b>Findings Analysis ({len(all_findings)} total)</b></summary>"
        analysis_html += "<div style='padding-left: 1rem; margin-top: 0.5rem;'>"
        
        # Show all findings grouped by type
        if by_type:
            analysis_html += "<div><b>🗂 All Findings by Type:</b></div>"
            for ftype, count in sorted(by_type.items(), key=lambda x: x[1], reverse=True):
                analysis_html += f"<details open style='margin-left: 1rem; margin-top: 0.5rem;'><summary><b>{ftype}</b> ({count} findings)</summary>"
                analysis_html += "<div style='padding-left: 1rem; margin-top: 0.25rem;'>"
                
                # Get all findings of this type
                type_findings = [f for f in all_findings if f.get('type') == ftype]
                
                for idx, finding in enumerate(type_findings, 1):
                    content = finding.get('content', {})
                    timestamp = finding.get('timestamp', 'N/A')[:19].replace('T', ' ')
                    
                    # Show relevant content based on type
                    if ftype == "page_discovery":
                        url = content.get('url', 'N/A')
                        elem_count = len(content.get('interactive_elements', []))
                        analysis_html += f"<div>{idx}. [{timestamp}] Found {elem_count} interactive elements at <code>{url}</code></div>"
                    elif ftype == "tech_fingerprint":
                        url = content.get('url', 'N/A')
                        techs = content.get('technologies', {})
                        tech_list = '<br/>'.join([f"&nbsp;&nbsp;&nbsp;- {k}: {v}" for k, v in techs.items()])
                        analysis_html += f"<div>{idx}. [{timestamp}] <code>{url}</code><br/>{tech_list}</div>"
                    elif ftype == "xss_potential":
                        url = content.get('url', 'N/A')
                        payload = content.get('payload', 'N/A')
                        elem = content.get('element', 'N/A')
                        analysis_html += f"<div>{idx}. [{timestamp}] 🔴 XSS at <code>{url}</code><br/>&nbsp;&nbsp;&nbsp;Element: {elem}, Payload: <code>{payload[:50]}</code></div>"
                    elif ftype == "error_disclosure":
                        url = content.get('url', 'N/A')
                        error = content.get('error', 'N/A')[:100]
                        payload = content.get('payload', 'N/A')
                        analysis_html += f"<div>{idx}. [{timestamp}] ⚠️ Error at <code>{url}</code><br/>&nbsp;&nbsp;&nbsp;Payload: <code>{payload[:50]}</code><br/>&nbsp;&nbsp;&nbsp;Error: {error}...</div>"
                    else:
                        # Generic display
                        content_str = str(content)[:150].replace('<', '&lt;').replace('>', '&gt;')
                        analysis_html += f"<div>{idx}. [{timestamp}] {content_str}...</div>"
                    
                    if idx < len(type_findings):
                        analysis_html += "<br/>"
                
                analysis_html += "</div></details>"
        
        # Show critical vulnerabilities
        if critical_vulns:
            analysis_html += f"<div style='margin-top: 0.5rem;'><b>⚠️ Critical/High Severity ({len(critical_vulns)}):</b></div>"
            for vuln in critical_vulns[:5]:  # Show first 5
                content = vuln.get('content', {})
                severity = vuln.get('severity', 'high')
                ftype = vuln.get('type', 'unknown')
                url = content.get('url', 'N/A')
                analysis_html += f"<div style='margin-left: 1rem;'>🔴 [{severity.upper()}] {ftype} at {url}</div>"
                if 'description' in content:
                    analysis_html += f"<div style='margin-left: 2rem;'>→ {content['description']}</div>"
                elif 'payload' in content:
                    analysis_html += f"<div style='margin-left: 2rem;'>→ Payload: {content['payload'][:50]}</div>"
            if len(critical_vulns) > 5:
                analysis_html += f"<div style='margin-left: 1rem;'>... and {len(critical_vulns) - 5} more</div>"
        else:
            analysis_html += "<div style='margin-top: 0.5rem;'>✅ No critical vulnerabilities detected</div>"
        
        analysis_html += "</div></details>"
        self.log_to_ui(analysis_html)
        
        summary = f"Found {len(all_findings)} total findings, {len(critical_vulns)} critical/high severity"
        self.planner.complete_task(task['id'], summary)    
    async def run_iteration(self, iteration_id: int, plan: dict):
        """Execute a single iteration of the mission plan."""
        self.log_to_ui(f"\n[Auto] 🔄 Starting Iteration Execution (ID: {iteration_id})")
        
        # Set up planner with iteration plan steps
        if plan.get('steps'):
            self.log_to_ui(f"[Auto] 📝 Loaded {len(plan['steps'])} steps from iteration plan")
            # Convert plan steps to planner tasks
            for step in plan['steps']:
                if isinstance(step, dict):
                    task_type = step.get('action', 'analyze')
                    target = step.get('target', self.planner.get_mission().get('target_url'))
                    description = step.get('description', str(step))
                else:
                    # Simple string step
                    task_type = 'analyze'
                    target = self.planner.get_mission().get('target_url')
                    description = str(step)
                
                self.planner.add_task(task_type, target, description)
        
        # Execute the iteration using the existing run_loop.
        # Off the event loop: run_loop blocks, and the API (including /stop) plus the
        # HITL approval round-trip both need the loop to stay responsive.
        await asyncio.get_event_loop().run_in_executor(None, self.run_loop)
        
        # Iteration complete - generate summary
        self.log_to_ui("\n[Auto] ✅ Iteration execution complete, generating summary...")
        summary = await self.summarize_iteration_findings(iteration_id)
        
        # Update iteration status in database
        if self.db:
            await self.db.update_iteration_status(iteration_id, "completed", summary)
            self.log_to_ui("[Auto] ✅ Iteration marked as completed")
        
        # Publish iteration_completed event for UI
        if hasattr(self, 'mission_id'):
            from backend.redis_manager import RedisManager
            redis_mgr = RedisManager()
            await redis_mgr.connect()
            
            # Get current iteration number
            iteration = await self.db.get_iteration(iteration_id)
            iteration_num = iteration.get('iteration_number', 1)
            
            await redis_mgr.publish_event("missions:all", {
                "type": "iteration_completed",
                "mission_id": self.mission_id,
                "iteration_number": iteration_num,
                "iteration_id": iteration_id,
                "summary": summary,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            })
            
            await redis_mgr.disconnect()
        
        return summary
    
    async def summarize_iteration_findings(self, iteration_id: int) -> str:
        """Generate a summary of findings from this iteration using LLM."""
        self.log_to_ui("[Auto] 📊 Aggregating findings for iteration summary...")
        
        # Get all findings (they're tagged with mission_id in repo)
        all_findings = self.repo.search_findings()
        
        # Count findings by type
        findings_by_type = {}
        for finding in all_findings:
            ftype = finding.get('type', 'unknown')
            findings_by_type[ftype] = findings_by_type.get(ftype, 0) + 1
        
        # Build summary prompt for LLM
        findings_summary = f"Total findings: {len(all_findings)}\n\n"
        findings_summary += "Breakdown by type:\n"
        for ftype, count in sorted(findings_by_type.items(), key=lambda x: x[1], reverse=True):
            findings_summary += f"- {ftype}: {count}\n"
        
        # Add details for critical findings
        critical = [f for f in all_findings if f.get('type') in ['xss_potential', 'error_disclosure', 'vulnerability']]
        if critical:
            findings_summary += f"\nCritical findings ({len(critical)}):\n"
            for f in critical[:5]:  # First 5
                findings_summary += f"- {f.get('type')}: {str(f.get('content', {}))[:100]}\n"
        
        # Use TacticalPlanner to generate summary
        try:
            from agents.planner import TacticalPlanner
            planner = TacticalPlanner()
            
            prompt = f"""
            Summarize the findings from this security testing iteration:
            
            {findings_summary}
            
            Provide a concise summary covering:
            1. What was discovered
            2. Any vulnerabilities or issues found
            3. What didn't work or was blocked
            4. Suggested focus areas for the next iteration
            
            Keep it under 300 words.
            """
            
            summary = planner._call_llm(prompt)
            self.log_to_ui("[Auto] ✅ Summary generated")
            return summary
            
        except Exception as e:
            self.log_to_ui(f"[Auto] ⚠️ Could not generate LLM summary: {e}")
            # Fallback to basic summary
            return findings_summary
    
    async def generate_next_iteration_plan(self, mission_id: int, current_iteration_num: int) -> int:
        """Generate and create the next iteration based on all previous findings."""
        self.log_to_ui(f"\n[Auto] 🔄 Generating Iteration {current_iteration_num + 1} plan...")
        
        if not self.db:
            raise Exception("Database required for iteration planning")
        
        # Get all previous iteration summaries
        all_summaries = await self.db.get_all_iteration_summaries(mission_id)
        
        # Get mission details
        mission = await self.db.get_mission(mission_id)
        target_url = mission.get('target_url')
        instructions = mission.get('instructions')
        
        # Generate new plan with LLM
        try:
            from agents.planner import TacticalPlanner
            planner = TacticalPlanner()
            
            # Get current page snapshot if browser is available
            triad = None
            if self.browser:
                try:
                    triad = self.browser.get_snapshot_triad()
                except:
                    pass
            
            prompt = f"""
            Mission: Security testing of {target_url}
            Instructions: {instructions}
            
            Previous Iterations Summary:
            {all_summaries}
            
            Current status: Iteration {current_iteration_num} complete.
            
            Create Iteration {current_iteration_num + 1} plan:
            - Focus on unexplored areas based on findings
            - Address any blockers from previous iterations
            - Try different approaches if previous methods failed
            - Prioritize finding sensitive data, credentials, or vulnerabilities
            - Don't repeat exact same tests that already failed
            
            Generate a tactical plan with specific steps.
            """
            
            new_plan = planner.generate_plan(
                goal=f"Iteration {current_iteration_num + 1}: Continue security testing",
                triad=triad,
                tech_report={},
                context=prompt
            )
            
            # Create new iteration in database
            next_iteration_id = await self.db.create_iteration(
                mission_id=mission_id,
                iteration_number=current_iteration_num + 1,
                plan=new_plan
            )
            
            self.log_to_ui(f"[Auto] ✅ Created Iteration {current_iteration_num + 1} (ID: {next_iteration_id})")
            return next_iteration_id
            
        except Exception as e:
            self.log_to_ui(f"[Auto] ❌ Failed to generate next iteration: {e}")
            raise
