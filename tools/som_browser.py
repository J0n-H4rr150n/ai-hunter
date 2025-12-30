import time
import json
from typing import Dict, Any, Tuple, List, Optional
from playwright.sync_api import sync_playwright, Page, ElementHandle, Response
from config.safety import SAFETY_LIMITS

class SoMBrowser:
    def __init__(self, headless=False, state_file=None):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=headless)
        
        # 1. CONTEXT SETUP WITH SAFETY & STATE
        self.context = self.browser.new_context(
            storage_state=state_file if state_file else None,
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        # Enforce Safety Timeouts
        self.context.set_default_timeout(SAFETY_LIMITS["NAV_TIMEOUT"])
        
        self.page: Page = self.context.new_page()
        self.element_cache: Dict[int, ElementHandle] = {}
        
        # 2. NETWORK SNIFFER INIT
        self.network_logs = []
        self.page.on("response", self._capture_network_traffic)

    # --- CORE NAVIGATION ---
    def navigate(self, url: str):
        try:
            print(f"[SafeBrowser] Navigating to {url}")
            self.page.goto(url, timeout=SAFETY_LIMITS["NAV_TIMEOUT"])
            self.page.wait_for_load_state("networkidle", timeout=SAFETY_LIMITS["NAV_TIMEOUT"])
        except Exception as e:
            print(f"[SafeBrowser] Warning: Navigation timed out or failed: {e}")
            # We don't crash, we just let the agent see the current partial state

    # --- THE TRIAD OF TRUTH ---
    def get_snapshot_triad(self) -> Dict[str, Any]:
        """
        Captures Visuals, Code, and Network in one go.
        """
        # 1. VISUAL (Set of Marks)
        screenshot, elements = self.inject_marks()
        
        # 2. CODE (Dynamic DOM + Raw Source)
        dom = self.page.content()
        try:
            # We use a separate request to get raw source to see comments/hidden fields
            # Short timeout because this is secondary intel
            raw_source = self.page.request.get(self.page.url).text()
        except:
            raw_source = "Raw source fetch failed (likely SPA or Auth wall)."

        # 3. NETWORK (Recent Logs)
        network_summary = self._get_recent_network_activity()

        return {
            "screenshot": screenshot,
            "elements": elements,
            "dom": dom,
            "raw_source": raw_source,
            "network": network_summary,
            "url": self.page.url
        }

    # --- STATE BRIDGE (For Fuzzer) ---
    def get_auth_state(self) -> Dict[str, Any]:
        """
        Exports current authentication (Cookies, LocalStorage, Headers) 
        so external tools like the Fuzzer can act as this user.
        """
        # Cookies
        cookies = {c['name']: c['value'] for c in self.context.cookies()}
        
        # Headers
        headers = {
            "User-Agent": self.page.evaluate("() => navigator.userAgent"),
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        # LocalStorage (Critical for JWTs)
        try:
            origins = self.page.evaluate("() => JSON.stringify(window.localStorage)")
            storage_dict = json.loads(origins)
            # JWT Heuristic
            for k, v in storage_dict.items():
                if "token" in k.lower() or "auth" in k.lower():
                    if v.startswith("eyJ"): # Standard JWT start
                        headers["Authorization"] = f"Bearer {v}"
        except:
            origins = "{}"

        return {
            "cookies": cookies,
            "headers": headers,
            "local_storage": origins
        }

    # --- INTERNALS: NETWORK SNIFFER ---
    def _capture_network_traffic(self, response: Response):
        try:
            # Filter noise (Images, CSS, Fonts)
            if response.request.resource_type not in ["fetch", "xhr", "document"]:
                return

            log_entry = {
                "url": response.url,
                "method": response.request.method,
                "status": response.status,
                "timestamp": time.time(),
                "body": None
            }

            # Capture JSON bodies
            try:
                if "application/json" in response.headers.get("content-type", ""):
                    log_entry["body"] = str(response.json())[:500] # Truncate
            except:
                pass

            self.network_logs.append(log_entry)
            # Keep buffer small
            if len(self.network_logs) > 50:
                self.network_logs.pop(0)
        except:
            pass

    def _get_recent_network_activity(self) -> str:
        if not self.network_logs: return "No recent XHR/Fetch."
        sorted_logs = sorted(self.network_logs, key=lambda x: x['timestamp'], reverse=True)
        summary = []
        for log in sorted_logs[:15]:
            summary.append(f"[{log['method']}] {log['status']} {log['url']} \n   Body: {log['body']}")
        return "\n".join(summary)

    # --- INTERNALS: VISUAL MARKING (SoM) ---
    def clean_marks(self):
        self.page.evaluate("() => { document.querySelectorAll('.som-marker').forEach(e => e.remove()); }")

    def inject_marks(self) -> Tuple[bytes, List[Dict]]:
        self.clean_marks()
        self.element_cache = {}

        js_script = """
        () => {
            const elements = Array.from(document.querySelectorAll('a, button, input, textarea, select, [role="button"], [onclick]'));
            const items = [];
            let counter = 0;

            elements.forEach(el => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);

                // Visibility Checks
                if (rect.width < 10 || rect.height < 10) return;
                if (style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0') return;
                if (rect.top < 0 || rect.left < 0 || rect.bottom > window.innerHeight || rect.right > window.innerWidth) return;

                // Occlusion Check (Simple center point check)
                const centerX = rect.left + rect.width / 2;
                const centerY = rect.top + rect.height / 2;
                const topEl = document.elementFromPoint(centerX, centerY);
                if (topEl && !el.contains(topEl) && !topEl.contains(el)) return;

                counter++;
                
                // Draw Marker
                const marker = document.createElement('div');
                marker.className = 'som-marker';
                marker.textContent = counter;
                marker.style.cssText = 'position:absolute;left:' + (rect.left+window.scrollX) + 'px;top:' + (rect.top+window.scrollY) + 'px;background:#FF0000;color:white;font-size:14px;font-weight:900;padding:2px 5px;z-index:2147483647;pointer-events:none;border:2px solid white;border-radius:3px;box-shadow:0 0 2px black;';
                document.body.appendChild(marker);
                
                items.push({
                    id: counter,
                    tagName: el.tagName.toLowerCase(),
                    text: el.innerText ? el.innerText.slice(0, 50).replace(/\\n/g, ' ') : '',
                    type: el.type || ''
                });
                
                el.setAttribute('data-som-id', counter);
            });
            return items;
        }
        """
        
        try:
            elements_metadata = self.page.evaluate(js_script)
        except Exception as e:
            print(f"[SoM] JS Injection failed: {e}")
            elements_metadata = []

        # Cache handles for interaction
        for meta in elements_metadata:
            eid = meta['id']
            handle = self.page.query_selector(f'[data-som-id="{eid}"]')
            if handle:
                self.element_cache[eid] = handle

        screenshot = self.page.screenshot(type="jpeg", quality=80)
        return screenshot, elements_metadata

    # --- INTERACTION ---
    def interact(self, action: str, element_id: int, value: str = None):
        if element_id not in self.element_cache:
            return f"Error: Element ID {element_id} not found."

        handle = self.element_cache[element_id]

        try:
            if action == "click":
                handle.click(timeout=SAFETY_LIMITS["NAV_TIMEOUT"])
                return f"Clicked ID {element_id}."
            elif action == "type":
                handle.fill(value, timeout=SAFETY_LIMITS["NAV_TIMEOUT"])
                return f"Typed '{value}' into ID {element_id}."
            else:
                return f"Unknown action {action}"
        except Exception as e:
            return f"Interaction failed: {str(e)}"

    def close(self):
        try:
            self.browser.close()
            self.playwright.stop()
        except:
            pass