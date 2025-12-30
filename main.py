import sys
import time
import asyncio
from config.config import Config
from core.quota_manager import QuotaManager
from memory.finding_repository import FindingRepository
from core.agent_tracker import AgentTracker
from core.human_interface import HumanInterface
from tools.tech_scanner import TechScanner
from tools.fuzzer import Fuzzer
from core.autonomous_loop import AutonomousLoop

def main():
    print("--------------------------------------------------")
    print("   🐝 HIVE MIND AGENT :: v1.1 AUTONOMOUS          ")
    print("--------------------------------------------------")
    
    # 1. Initialize Core Systems
    print("[Init] Loading Quota Manager...")
    quota = QuotaManager(agent_id="global_profile")
    
    print("[Init] Connecting to Finding Repository (Hive Memory)...")
    repo = FindingRepository()
    
    print("[Init] Starting Agent Tracker (Shadow Logging)...")
    tracker = AgentTracker(agent_id="hive_worker_01")
    
    print("[Init] Establish Human Interface...")
    interface = HumanInterface(tracker)
    
    # 2. Initialize Manual Tools (for CLI usage)
    scanner = TechScanner(repo, quota)
    fuzzer = Fuzzer(repo, quota)
    
    # 3. Initialize Autonomous Brain
    # This is the new engine that drives the agent automatically
    auto_pilot = AutonomousLoop(tracker, repo, quota)
    
    # 4. Command Loop
    print("\n[✅ System Ready]")
    interface.notify(f"Session shadowing to: {tracker.get_session_path()}")
    print("Commands:")
    print("  auto <url> [instructions]  : Start autonomous mission with optional guidance")
    print("                              Example: auto http://site.com \"Focus on IDs, skip signups\"")
    print("  scan <url>                 : Manual scan")
    print("  fuzz <url>                 : Manual fuzz")
    print("  search <txt>               : Search memory")
    print("  status                     : Check quota")
    print("  exit                       : Shutdown")
    
    while True:
        try:
            # use the interface to get input (logs the interaction)
            user_input = interface.ask("Awaiting directive...")
            
            if not user_input:
                continue
                
            parts = user_input.split()
            cmd = parts[0].lower()
            
            # --- EXIT ---
            if cmd in ["exit", "quit"]:
                print("[🐝] Shutting down. syncing state...")
                break
            
            # --- AUTONOMOUS MODE ---
            elif cmd == "auto":
                if len(parts) < 2:
                    print("Usage: auto <url> [instructions in quotes]")
                    print("Example: auto http://site.com \"Focus on ID params, don't create accounts\"")
                    continue
                    
                target = parts[1]
                goal = f"Audit {target} for vulnerabilities"
                
                # Check if instructions were provided (everything after the URL)
                instructions = None
                if len(parts) > 2:
                    # Join remaining parts as instructions
                    instructions = " ".join(parts[2:])
                    # Remove quotes if present
                    instructions = instructions.strip('"').strip("'")
                
                # Hand over control to the Autonomous Loop
                asyncio.run(auto_pilot.start_mission(goal, target, instructions))
                
                print("\n[✅] Mission Loop Finished. Returning to manual control.")

            # --- MANUAL COMMANDS ---
            elif cmd == "scan":
                if len(parts) < 2:
                    print("Usage: scan <url>")
                    continue
                url = parts[1]
                tracker.capture_shadow("cmd_scan_start", {"target": url})
                print(f"[Agent] Initiating passive scan on {url}...")
                scanner.scan_url(url)
                
            elif cmd == "fuzz":
                if len(parts) < 2:
                    print("Usage: fuzz <url>")
                    continue
                url = parts[1]
                tracker.capture_shadow("cmd_fuzz_start", {"target": url})
                print(f"[Agent] Starting active fuzzing on {url}...")
                fuzzer.fuzz_url_params(url)
                
            elif cmd == "search":
                if len(parts) < 2:
                    print("Usage: search <natural language query>")
                    continue
                query = " ".join(parts[1:])
                print(f"[Memory] Searching hive for: '{query}'...")
                results = repo.semantic_search(query, limit=3)
                if results:
                    for i, r in enumerate(results):
                        print(f" {i+1}. [{r.get('type')}] {r.get('source')} -> {str(r.get('content'))[:50]}...")
                else:
                    print("[Memory] No relevant findings found.")

            elif cmd == "status":
                status = quota.get_status()
                print("\n--- Resource Usage ---")
                for k, v in status.items():
                    print(f"{k}: {v}")
                print("----------------------")
                
            else:
                print("Unknown command. Type 'auto <url>' to start.")
                
        except KeyboardInterrupt:
            print("\n[🐝] Force stopping...")
            break
        except Exception as e:
            print(f"[❌] Critical Error: {e}")
            # Capture the error state visually
            tracker.capture_shadow("error_state", {"error": str(e)})

if __name__ == "__main__":
    main()