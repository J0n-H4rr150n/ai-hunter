import json
from core.llm_client import LocalModel
from config.config import Config

class FindingsAnalyst:
    def __init__(self, recorder=None):
        self.model = LocalModel(
            Config.LLM_MODEL,
            recorder=recorder,
            agent_name="FindingsAnalyst",
            system_instruction="""You are a Senior Security Analyst (SOC Tier 3) and CTF Expert.
            
            YOUR JOB:
            Review "Candidate Findings" reported by automated agents to determine if they are TRUE POSITIVES.
            
            WHAT TO LOOK FOR:
            1. CTF Flags: Specific patterns like `flag{...}`, `CTF{...}`, `XBEN{...}`, or `b64 encoded` strings that decode to flags.
            2. PII/Sensitive Data: Credit cards, SSNs, Address lists, leaked Admin session tokens.
            3. Logic Errors: Accessing User B's data while logged in as User A (IDOR).
            4. Leaked Credentials: Hardcoded passwords in comments or config objects.
            
            INPUT:
            - Agent Notes: Why the automated bot thought this was interesting.
            - Evidence: The raw text, HTML snippet, or JSON response.
            
            OUTPUT JSON SCHEMA:
            {
                "verdict": "CONFIRMED" | "FALSE_POSITIVE" | "NEEDS_HUMAN",
                "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO",
                "finding_name": "Short Title (e.g. IDOR on Order 105)",
                "explanation": "Technical justification for your verdict.",
                "extracted_secret": "The actual flag string or secret value found (if any). Empty string if none."
            }
            
            BEHAVIOR:
            - If you see a flag format (e.g. `flag{123}`), verdict is ALWAYS "CONFIRMED".
            - If the evidence is just a standard 404 or 403 error page, verdict is "FALSE_POSITIVE".
            - If the evidence is ambiguous (e.g. a weird hash), verdict is "NEEDS_HUMAN".
            """
        )

    def review_candidate(self, candidate: dict) -> dict:
        """
        Reviews a single finding candidate.
        
        Args:
            candidate: {
                "tool": str,
                "location": str,
                "agent_notes": str,
                "evidence": str
            }
        """
        prompt = f"""
        --- CANDIDATE REPORT ---
        Source Tool: {candidate.get('tool', 'unknown')}
        Location: {candidate.get('location', 'unknown')}
        
        --- AGENT NOTES ---
        {candidate.get('agent_notes', 'No notes provided.')}
        
        --- RAW EVIDENCE ---
        {candidate.get('evidence', '')[:10000]} 
        
        --- INSTRUCTIONS ---
        Analyze the evidence above. Is this a valid security finding?
        Output JSON only.
        """
        
        try:
            response = self.model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            return json.loads(response.text)
        except Exception as e:
            # Fallback if the model hallucinates invalid JSON or errors out
            return {
                "verdict": "NEEDS_HUMAN",
                "severity": "UNKNOWN", 
                "finding_name": "Analyst Error", 
                "explanation": f"Model failed to parse or execute: {str(e)}",
                "extracted_secret": ""
            }