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
            f"CURRENT GOAL: {goal}",
            f"--- MISSION PLAN (EXECUTE THIS) ---\n{self.current_mission_plan}\n",
            
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