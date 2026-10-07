import json
from core.llm_client import LocalModel, Part
from config.safety import HARD_CAPS
from config.config import Config

class TacticalPlanner:
    def __init__(self):
        self.model = LocalModel(Config.LLM_MODEL)
        
    def generate_plan(self, goal: str, triad: dict, tech_report: dict) -> dict:
        """
        Synthesizes Tech Stack + Visuals + Network into a Master Plan.
        
        Args:
            goal: The user's objective (e.g. "Find the flag").
            triad: Dictionary containing 'screenshot' (bytes), 'network' (str), 'raw_source' (str).
            tech_report: Dictionary from TechScanner containing framework/server details.

        Returns a dictionary with:
        {
            "rationale": "Why we are doing this",
            "steps": "1. Step one\n2. Step two...",
            "budgets": {"run_intruder": 3, "click": 20}
        }
        """
        
        # Format the Tech Report for the LLM
        tech_str = f"""
        SERVER: {tech_report.get('server', 'Unknown')}
        FRAMEWORKS: {', '.join(tech_report.get('framework', []))}
        LANG HINT: {tech_report.get('lang', 'Unknown')}
        SECURITY HEADERS: {tech_report.get('interesting_headers', {})}
        FINDINGS: {tech_report.get('findings', [])}
        """

        prompt = [
            f"MISSION GOAL: {goal}",
            f"TARGET URL: {triad.get('url', 'Unknown')}",
            "--- STEP 1: TECH STACK ANALYSIS ---",
            tech_str,
            "--- STEP 2: RECON DATA ---",
            f"Network Snippet: {str(triad.get('network', ''))[:500]}...",
            f"Raw Source Snippet: {str(triad.get('raw_source', ''))[:500]}...",
            
            "--- INSTRUCTIONS ---",
            "1. Analyze the Tech Stack & Recon Data.",
            "2. Create a specific Execution Plan. Be precise (e.g. 'Check /wp-json' instead of 'Check API').",
            "3. ESTIMATE RESOURCE BUDGETS. You have a Hard Cap.",
            f"   HARD CAPS: {json.dumps(HARD_CAPS)}",
            "   Don't ask for max unless needed. Be efficient.",
            "4. OUTPUT STRICT JSON ONLY.",
            
            Part.from_data(triad['screenshot'], mime_type="image/jpeg"),
            
            """JSON SCHEMA:
            {
                "rationale": "Brief strategy summary",
                "steps": "Numbered execution steps",
                "budgets": {
                    "run_intruder": int,
                    "check_network": int,
                    "navigate": int,
                    "click": int,
                    "type": int,
                    "view_dom": int,
                    "view_raw_source": int
                }
            }
            """
        ]
        
        # Print removed - logged by autonomous_loop instead
        try:
            response = self.model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            return json.loads(response.text)
        except Exception as e:
            print(f"[Planner Error] {e}")
            # Fallback safe plan to prevent crash
            return {
                "rationale": "Fallback due to generation error.",
                "steps": "1. Explore manually using DOM and Source checks.\n2. Report any findings.",
                "budgets": {} # Will trigger defaults in QuotaManager
            }