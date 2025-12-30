# config/safety.py

# 1. PARAMETER LIMITS (Immutable physics of the engine)
# These are code-level constraints that the LLM cannot override.
SAFETY_LIMITS = {
    "FUZZER_MAX_RANGE": 50,       # Max IDs to scan in one batch (e.g., 1-50)
    "FUZZER_MAX_CONCURRENCY": 5,  # Max threads/connections
    "FUZZER_DELAY": 0.5,          # Seconds between batches (Rate Limiting)
    "FUZZER_TIMEOUT": 5.0,        # Seconds before dropping a request
    "NAV_TIMEOUT": 10000,         # 10s max for page loads (Playwright)
    "MAX_DOM_CHARS": 20000,       # Truncate DOM/Source before sending to Gemini to save tokens
}

# 2. HARD CAPS (The "Ceiling")
# The Planner cannot request more than this per phase, even if it wants to.
HARD_CAPS = {
    "run_intruder": 5,        # Absolute Max fuzzing runs per phase
    "check_network": 20,
    "navigate": 20,
    "click": 50,
    "type": 50,
    "view_dom": 100,
    "view_raw_source": 20,
    "report_finding": 100     # Reporting is always cheap
}

# 3. DEFAULT BUDGETS (The "Floor")
# Used if the Planner fails to specify a budget or errors out.
DEFAULT_BUDGETS = {
    "run_intruder": 1,        # Conservative default
    "check_network": 5,
    "navigate": 10,
    "click": 20,
    "type": 20,
    "view_dom": 30,
    "view_raw_source": 5,
    "report_finding": 100
}

def sanitize_fuzz_range(start: int, end: int) -> tuple[int, int, str]:
    """
    Clamps a requested range to safe limits defined in SAFETY_LIMITS.
    Returns: (safe_start, safe_end, warning_message)
    """
    try:
        start = int(start)
        end = int(end)
    except:
        return 1, 5, "Invalid integers provided. Reset to default 1-5."

    # 1. Ensure logical order
    if start > end:
        start, end = end, start
    
    # 2. Calculate requested size
    size = end - start + 1
    
    # 3. Clamp if too large
    msg = ""
    limit = SAFETY_LIMITS["FUZZER_MAX_RANGE"]
    
    if size > limit:
        original_end = end
        end = start + limit - 1
        msg = f"SAFETY CLAMP: Requested range size {size} exceeded limit {limit}. Truncated end from {original_end} to {end}."
    
    return start, end, msg

def truncate_context(text: str) -> str:
    """
    Safely truncates huge text blobs (DOM/Source) to prevent token overflow.
    """
    if not text:
        return ""
        
    limit = SAFETY_LIMITS["MAX_DOM_CHARS"]
    
    if len(text) > limit:
        truncated_amount = len(text) - limit
        return text[:limit] + f"\n...[TRUNCATED BY SAFETY GUARDRAIL: {truncated_amount} chars removed]..."
        
    return text