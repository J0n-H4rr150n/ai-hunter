import json
import vertexai
from vertexai.generative_models import GenerativeModel, Part, SafetySetting
from config.safety import truncate_context, SAFETY_LIMITS
from config.config import Config

class VertexAgent:
    def __init__(self):
        vertexai.init(project=Config.GCP_PROJECT_ID, location=Config.GCP_LOCATION)
        
        # The agent starts with no memory or plan. 
        # These are injected by the Orchestrator at runtime.
        self.memory = None 
        self.current_mission_plan = "No specific plan loaded. Explore safely."
        self.runbook_context = None  # Injected when executing via runbooks
        
        self.model = GenerativeModel(
            "gemini-2.5-pro",
            system_instruction="""You are an Elite Web Security Automation Agent.
            
            YOUR MISSION:
            Execute the provided MISSION PLAN step-by-step to find flags, vulnerabilities, or specific data.
            
            TOOLS AVAILABLE:
            1. INTERACTION:
               - "click": requires "element_id" (int).
               - "type": requires "element_id" (int) and "value" (string).
               - "navigate": requires "value" (url string).
            
            2. RECONNAISSANCE:
               - "view_raw_source": Returns raw server HTML. Use to find comments/hidden inputs.
               - "check_network": Returns recent JSON API logs. Use to find data leaks or IDOR targets.
               - "view_dom": Returns the current rendered DOM.
            
            3. HEAVY WEAPONS (Use sparingly):
               - "run_intruder": Fuzzes a range of IDs. 
                 Requires: "value" (url template with {FUZZ}), "start_id" (int), "end_id" (int).
            
            4. REPORTING:
               - "report_finding": Use this IMMEDIATEY when you find a flag or secret.
                 Requires: "value" (short desc), "evidence" (the flag/secret string).
               - "replan": Use this if you are stuck or out of resources.
               - "done": Use this when the Goal is fully achieved.

            OUTPUT FORMAT (JSON ONLY):
            {
                "thought": "Reasoning based on Plan + Observation + Past Lessons",
                "action": "tool_name",
                "element_id": int or null,
                "value": string or null,
                "start_id": int or null,
                "end_id": int or null,
                "evidence": string or null
            }
            """
        )
        
        # Allow security testing content (prevent false positive blocks)
        self.safety = [
            SafetySetting(
                category=SafetySetting.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=SafetySetting.HarmBlockThreshold.BLOCK_ONLY_HIGH,
            ),
            SafetySetting(
                category=SafetySetting.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                threshold=SafetySetting.HarmBlockThreshold.BLOCK_ONLY_HIGH,
            ),
            SafetySetting(
                category=SafetySetting.HarmCategory.HARM_CATEGORY_HARASSMENT,
                threshold=SafetySetting.HarmBlockThreshold.BLOCK_ONLY_HIGH,
            ),
            SafetySetting(
                category=SafetySetting.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                threshold=SafetySetting.HarmBlockThreshold.BLOCK_ONLY_HIGH,
            ),
        ]

    def set_mission_plan(self, plan_text: str):
        """
        Injects the Tactical Planner's output into the system context.
        """
        self.current_mission_plan = plan_text
    
    def set_runbook_context(self, runbook_name: str, runbook_metadata: dict, 
                           current_step: dict, completed_steps: list,
                           findings_so_far: list):
        """
        Inject runbook execution context for agent awareness.
        
        When executing via runbooks, the agent should understand:
        - What runbook is being followed
        - What step we're currently on
        - What has been completed
        - What findings have been made
        - What the runbook's goal is
        
        This allows the agent to make intelligent decisions aligned with
        the runbook's strategy while still being autonomous.
        """
        self.runbook_context = {
            'runbook_name': runbook_name,
            'runbook_goal': runbook_metadata.get('goal', 'Execute runbook steps'),
            'runbook_category': runbook_metadata.get('category', 'general'),
            'current_step': current_step,
            'current_step_id': current_step.get('id'),
            'current_step_name': current_step.get('name', ''),
            'current_step_goal': current_step.get('description', ''),
            'completed_steps': [s.get('id') for s in completed_steps],
            'completed_step_names': [s.get('name') for s in completed_steps],
            'findings_count': len(findings_so_far),
            'recent_findings': findings_so_far[-5:] if findings_so_far else []
        }
    
    def clear_runbook_context(self):
        """Clear runbook context when switching to free-form mode"""
        self.runbook_context = None

    def plan_next_step(self, goal: str, history: list, screenshot_bytes: bytes, element_list: list, text_context: str = None) -> dict:
        """
        The Core Loop:
        1. Checks Memory (RAG) for past mistakes.
        2. Sanitizes inputs (Safety truncation).
        3. Generates the next move via Gemini.
        """
        
        # 1. MEMORY RAG STEP
        # Retrieve relevant lessons based on the last action/thought
        rag_context = ""
        if self.memory and history:
            last_entry = history[-1]
            # Search for lessons relevant to what we just did or thought
            query = f"{last_entry.get('thought', '')} {last_entry.get('action', '')}"
            rag_context = self.memory.retrieve_relevant_lessons(query, last_entry.get('action', 'general'))

        # 2. DATA SANITIZATION (Guardrail)
        if text_context:
            text_context = truncate_context(text_context)

        # 3. PROMPT CONSTRUCTION
        # Compact element list to save tokens
        element_context = "\n".join([
            f"ID {e['id']}: <{e['tagName']}> {e.get('text', '')[:50]}" 
            for e in element_list
        ])
        
        prompt_parts = [
            f"CURRENT GOAL: {goal}",        ]
        
        # Inject runbook context if we're in runbook mode
        if self.runbook_context:
            runbook_info = f"""--- RUNBOOK EXECUTION MODE ---
Runbook: {self.runbook_context['runbook_name']}
Runbook Goal: {self.runbook_context['runbook_goal']}
Category: {self.runbook_context['runbook_category']}

CURRENT STEP #{self.runbook_context['current_step_id']}: {self.runbook_context['current_step_name']}
Step Objective: {self.runbook_context['current_step_goal']}

Completed Steps: {', '.join(self.runbook_context['completed_step_names']) if self.runbook_context['completed_step_names'] else 'None yet'}

Findings So Far: {self.runbook_context['findings_count']} findings collected
Recent Findings: {json.dumps(self.runbook_context['recent_findings'][-3:]) if self.runbook_context['recent_findings'] else 'None yet'}

IMPORTANT: Your actions should align with the current step's objective while using your intelligence to adapt to what you observe.
--- END RUNBOOK CONTEXT ---
"""
            prompt_parts.append(runbook_info)
        
        prompt_parts.extend([            f"--- MISSION PLAN (EXECUTE THIS) ---\n{self.current_mission_plan}\n",
            
            # Inject RAG context if it exists
            (rag_context if rag_context else ""),
            
            f"HISTORY: {json.dumps(history[-3:])}", # Keep only recent history to focus attention
            f"INTERACTIVE ELEMENTS:\n{element_context}",
            
            # The Visual Anchor
            Part.from_data(screenshot_bytes, mime_type="image/jpeg")
        ]

        if text_context:
            prompt_parts.append(f"--- CONTEXT DATA (Source/Network) ---\n{text_context}\n--- END DATA ---")

        prompt_parts.append("Decide the next move. Output valid JSON.")

        # 4. GENERATION
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
                "thought": "Error generating response. I will wait.",
                "action": "wait",
                "value": str(e)
            }
    
    def plan_next_step_from_runbook(self, runbook_step: dict, 
                                    step_context: dict,
                                    screenshot_bytes: bytes, 
                                    element_list: list,
                                    text_context: str = None) -> dict:
        """
        Specialized planning for runbook-guided execution.
        
        This method helps the agent understand and execute a specific runbook step
        while maintaining autonomy to adapt based on what it observes.
        
        Args:
            runbook_step: The current runbook step dict with action, description, etc.
            step_context: Additional context about findings, history, etc.
            screenshot_bytes: Current screenshot
            element_list: Interactive elements on page
            text_context: Optional text context (source, network logs, etc.)
        
        Returns:
            dict: Agent decision in standard action format
        """
        
        # Extract step information
        step_id = runbook_step.get('id')
        step_name = runbook_step.get('name', 'Unnamed Step')
        step_action = runbook_step.get('action', 'unknown')
        step_description = runbook_step.get('description', '')
        step_tool = runbook_step.get('tool', 'agent')
        
        # Get context
        findings_so_far = step_context.get('findings', [])
        history = step_context.get('history', [])
        goal = step_context.get('goal', 'Execute runbook step')
        
        # Memory RAG (if available)
        rag_context = ""
        if self.memory and history:
            last_entry = history[-1] if history else {}
            query = f"{step_description} {step_action}"
            rag_context = self.memory.retrieve_relevant_lessons(query, step_action)
        
        # Data sanitization
        if text_context:
            text_context = truncate_context(text_context)
        
        # Compact elements
        element_context = "\n".join([
            f"ID {e['id']}: <{e['tagName']}> {e.get('text', '')[:50]}" 
            for e in element_list
        ])
        
        # Build runbook-specific prompt
        prompt_parts = [
            f"=== RUNBOOK-GUIDED EXECUTION ===",
            f"Overall Goal: {goal}",
            f"",
            f"CURRENT RUNBOOK STEP:",
            f"  Step #{step_id}: {step_name}",
            f"  Objective: {step_description}",
            f"  Suggested Action: {step_action}",
            f"  Tool Hint: {step_tool}",
            f"",
            f"FINDINGS SO FAR: {len(findings_so_far)} findings collected",
        ]
        
        if findings_so_far:
            recent = findings_so_far[-3:]
            prompt_parts.append(f"Recent Findings:")
            for finding in recent:
                title = finding.get('title', 'Untitled')
                prompt_parts.append(f"  - {title}")
        
        prompt_parts.extend([
            f"",
            f"YOUR TASK:",
            f"Execute the runbook step's objective using your intelligence and the available tools.",
            f"The runbook provides GUIDANCE, but YOU must make the actual decisions based on what you observe.",
            f"",
            f"If the suggested action is '{step_action}', consider how to accomplish that given the current page state.",
            f"You may need to adapt if the page looks different than expected.",
            f"",
        ])
        
        # Add RAG context
        if rag_context:
            prompt_parts.append(f"RELEVANT PAST LESSONS:\n{rag_context}\n")
        
        # Add history
        if history:
            prompt_parts.append(f"RECENT HISTORY: {json.dumps(history[-3:])}")
        
        # Add current state
        prompt_parts.extend([
            f"",
            f"INTERACTIVE ELEMENTS ON PAGE:",
            element_context,
            f"",
            Part.from_data(screenshot_bytes, mime_type="image/jpeg")
        ])
        
        # Add text context if available
        if text_context:
            prompt_parts.append(f"--- CONTEXT DATA (Source/Network) ---\n{text_context}\n--- END DATA ---")
        
        prompt_parts.append("Decide your next action to accomplish this runbook step. Output valid JSON.")
        
        # Generate decision
        try:
            response = self.model.generate_content(
                prompt_parts,
                generation_config={"response_mime_type": "application/json"},
                safety_settings=self.safety
            )
            decision = json.loads(response.text)
            
            # Enhance decision with runbook metadata
            decision['runbook_step_id'] = step_id
            decision['runbook_step_name'] = step_name
            decision['runbook_guided'] = True
            
            return decision
            
        except Exception as e:
            print(f"[Agent Brain Error - Runbook Mode] {e}")
            return {
                "thought": f"Error planning runbook step. Will try a simple approach for: {step_description}",
                "action": "wait",
                "value": str(e),
                "runbook_step_id": step_id,
                "runbook_guided": True
            }
