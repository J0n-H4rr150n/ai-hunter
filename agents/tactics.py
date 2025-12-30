# agents/tactics.py
# This file serves as the "Knowledge Base" for the Tactical Planner.
# It defines specific methodologies ("Tactics") that the Planner selects from
# to build the Mission Plan.

TACTICS_KNOWLEDGE = """
[TACTIC: RECON_STATIC]
- DESCRIPTION: Passive analysis of client-side code to find hardcoded secrets or config.
- ACTION 1: Use 'view_raw_source' to retrieve the server-side HTML (before JS execution).
- PATTERNS: Look for HTML comments (<!-- -->), hidden inputs (<input type="hidden">), and variable assignments (const config = ...).
- KEYWORDS: 'admin', 'password', 'flag', 'test', 'dev', 'staging', 'api_key'.

[TACTIC: RECON_NETWORK]
- DESCRIPTION: Sniffing backend API traffic to find data leakage or IDOR targets.
- ACTION 1: Use 'check_network' to view recent JSON XHR/Fetch responses.
- HEURISTIC 1: Look for JSON fields that are NOT rendered in the UI (e.g., "is_admin": false, "user_role": "guest").
- HEURISTIC 2: Look for numeric IDs in URL paths (e.g., /api/orders/30111) or query params (?id=50).

[TACTIC: AUTH_BYPASS]
- DESCRIPTION: Techniques to bypass login forms without valid credentials.
- METHOD 1 (Source Leak): Check 'RECON_STATIC' for 'Dev Notes' containing default credentials.
- METHOD 2 (SQL Injection): Try inputting "admin' OR '1'='1" (or variants like "admin' #") into the username field.
- METHOD 3 (Default Creds): Try standard pairs: admin/admin, admin/password, root/toor, user/user, test/test.
- METHOD 4 (No-Auth): Check if the URL structure allows direct access to dashboards (e.g., changing /login to /admin).

[TACTIC: IDOR_FUZZING]
- DESCRIPTION: Enumerating Insecure Direct Object References to access other users' data.
- TRIGGER: You see a numeric ID in an API or URL (e.g. /orders/30111) but manual guessing (+1/-1) fails or is tedious.
- ACTION: Use the 'run_intruder' tool.
- CONFIGURATION:
  - Template: Construct a URL like `http://host/api/orders/{FUZZ}`.
  - Range: If you see 30111, fuzz 30100-30150. ALSO fuzz 1-50 (Admin/System IDs often live here).
- ANALYSIS: The tool will auto-filter boring responses. Focus on the anomalies (different Content-Length or Status Code).

[TACTIC: SHOPPING_LOGIC]
- DESCRIPTION: Exploiting business logic flaws in e-commerce workflows.
- METHOD 1 (Negative Price): Can you add an item with quantity -1?
- METHOD 2 (Currency Swap): Can you change the currency param in the API request?
- METHOD 3 (Cart Price): Does the API trust the price sent from the client?

[TACTIC: REACT_SPA_ANALYSIS]
- DESCRIPTION: Specific handling for Single Page Applications (React/Vue/Angular).
- NOTE: 'view_raw_source' will likely be empty (<div id="root">). Rely on 'view_dom' and 'check_network'.
- METHOD: Look for '.map' files in the network tab (Source Maps) which can reconstruct the original source code.
- METHOD: Check LocalStorage for JWT tokens or user state.
"""

def get_tactic_by_name(name):
    """Helper to retrieve a specific tactic block."""
    try:
        start_tag = f"[TACTIC: {name}]"
        start_idx = TACTICS_KNOWLEDGE.index(start_tag)
        # Find next tactic or end of string
        next_tag_idx = TACTICS_KNOWLEDGE.find("[TACTIC:", start_idx + 1)
        
        if next_tag_idx == -1:
            return TACTICS_KNOWLEDGE[start_idx:].strip()
        else:
            return TACTICS_KNOWLEDGE[start_idx:next_tag_idx].strip()
    except ValueError:
        return None