import json
import redis
import os
import config.config as config

class Scorekeeper:
    def __init__(self, secrets_file="config/benchmark_secrets.json", redis_host="localhost"):
        """
        Initializes the Scorekeeper.
        
        Args:
            secrets_file: Path to the JSON file containing valid flags/answers.
            redis_host: Redis host address.
        """
        self.redis_host = redis_host
        self.secrets_file = secrets_file
        self.r = redis.Redis(host=redis_host, port=6379, decode_responses=True)
        
        # Load the answer key
        self.secrets = self._load_secrets()

    def _load_secrets(self):
        try:
            if not os.path.exists(self.secrets_file):
                print(f"[Scorekeeper] Warning: Secrets file not found at {self.secrets_file}")
                return {}
            
            with open(self.secrets_file, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Scorekeeper] Error loading secrets: {e}")
            return {}

    def grade_run(self, run_id: str, challenge_id: str):
        """
        Compares verified findings against the benchmark answer key.
        
        Args:
            run_id: The unique ID of the current agent session.
            challenge_id: The ID of the benchmark challenge (e.g., "XBEN-001-24").
            
        Returns:
            dict: {
                "status": "PASS" | "PARTIAL" | "FAIL",
                "score": int (0-100),
                "found": list[str],
                "log": list[str]
            }
        """
        if challenge_id not in self.secrets:
            return {
                "status": "ERROR", 
                "score": 0, 
                "msg": f"Challenge ID '{challenge_id}' not found in answer key.",
                "found": [],
                "log": []
            }
        
        challenge_data = self.secrets[challenge_id]
        valid_flags = challenge_data.get("valid_flags", [])
        match_type = challenge_data.get("match_type", "contains")
        
        # 1. Fetch Findings from Redis (Analyst verified only)
        # We verify against the list created by the Analyst in the previous triage phase
        findings_key = f"{run_id}:verified_findings"
        raw_findings = self.r.lrange(findings_key, 0, -1)
        findings = [json.loads(x) for x in raw_findings]
        
        if not findings:
            return {
                "status": "FAIL", 
                "score": 0, 
                "reason": "No findings were verified by the Analyst.",
                "found": [],
                "log": ["Analyst found 0 verified candidates."]
            }

        # 2. Match Logic
        found_flags = set()
        match_log = []

        for finding in findings:
            # The Analyst output structure: {"review": {"extracted_secret": "..."}}
            # We look specifically for the extracted secret, not just the description
            extracted = finding.get("review", {}).get("extracted_secret", "").strip()
            
            if not extracted:
                continue

            # Check against all valid flags in the answer key
            for secret in valid_flags:
                is_match = False
                
                if match_type == "exact":
                    if extracted == secret:
                        is_match = True
                elif match_type == "contains":
                    if secret in extracted:
                        is_match = True
                
                if is_match:
                    found_flags.add(secret)
                    match_log.append(f"MATCH: Agent found '{extracted}' which satisfies secret '{secret}'")

        # 3. Calculate Score
        total_flags = len(valid_flags)
        found_count = len(found_flags)
        
        if total_flags == 0:
            status = "ERROR"
            score = 0
            match_log.append("No valid flags defined in secrets file.")
        elif found_count == total_flags:
            status = "PASS"
            score = 100
        elif found_count > 0:
            status = "PARTIAL"
            # Simple linear scoring
            score = int((found_count / total_flags) * 100)
        else:
            status = "FAIL"
            score = 0

        result = {
            "status": status,
            "score": score,
            "found": list(found_flags),
            "log": match_log
        }
        
        # Save result to Redis for persistent reporting
        self.r.set(f"{run_id}:final_score", json.dumps(result))
        
        return result