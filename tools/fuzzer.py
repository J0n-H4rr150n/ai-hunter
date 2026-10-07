import requests
import random
import string
import time
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from config.config import Config
from config.safety import SAFETY_LIMITS

class Fuzzer:
    """
    A simple fuzzing tool for the agent.
    Generates malformed inputs to test web endpoints for stability or vulnerabilities.
    Integrates with QuotaManager to respect rate limits and FindingRepository to store results.
    """

    # Basic payloads for common injection/error triggering
    PAYLOADS = [
        "' OR '1'='1",
        "<script>alert(1)</script>",
        "{{7*7}}",
        "../../etc/passwd",
        "\x00",
        "A" * 1000,  # Buffer overflow attempt
        "%00",
        "admin' --",
        "true",
        "false",
        "null",
        "NaN",
        "Infinity"
    ]

    def __init__(self, finding_repo, quota_manager):
        """
        Args:
            finding_repo: Instance of FindingRepository to save discoveries.
            quota_manager: Instance of QuotaManager to track request usage.
        """
        self.repo = finding_repo
        self.quota = quota_manager
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'HiveMindAgent-Fuzzer/1.0'
        })

    def fuzz_url_params(self, url: str, intensity: int = 5):
        """
        Fuzzes the query parameters of a given URL.

        Args:
            url (str): The target URL (e.g., http://example.com/search?q=test)
            intensity (int): Number of mutations to try per parameter.
        """
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        if not params:
            print(f"[Fuzzer] No parameters found to fuzz in: {url}")
            return

        print(f"[Fuzzer] Starting fuzzing on {url} ({len(params)} params, intensity {intensity})")

        for param_name in params.keys():
            # Try a mix of predefined payloads and random noise
            test_payloads = random.sample(self.PAYLOADS, min(len(self.PAYLOADS), intensity))
            
            # Add some random garbage data
            for _ in range(2):
                test_payloads.append(''.join(random.choices(string.printable, k=10)))

            for payload in test_payloads:
                # check quota before every request
                if not self.quota.check_limit("actions"):
                    print("[Fuzzer] 🛑 Quota exceeded. Stopping fuzzing.")
                    return

                # Construct new URL with fuzzed param
                fuzzed_params = params.copy()
                fuzzed_params[param_name] = [payload] # Replace value
                
                query_string = urlencode(fuzzed_params, doseq=True)
                target_url = urlunparse((
                    parsed.scheme, parsed.netloc, parsed.path, 
                    parsed.params, query_string, parsed.fragment
                ))

                self._send_request(target_url, payload, param_name)

    def _send_request(self, url, payload, param_name):
        """
        Sends the request and analyzes the response.
        """
        try:
            start_time = time.time()
            response = self.session.get(url, timeout=SAFETY_LIMITS['FUZZER_TIMEOUT'])
            latency = time.time() - start_time

            # Log the action cost
            self.quota.tally("actions", 1)

            status = response.status_code
            
            # Simple heuristic for "interesting" results
            is_interesting = False
            finding_type = "fuzz_result"

            if 500 <= status < 600:
                is_interesting = True
                print(f"[Fuzzer] 💥 Server Error ({status}) at {url}")
                finding_type = "vulnerability_crash"
            
            elif latency > 2.0:
                is_interesting = True
                print(f"[Fuzzer] 🐢 High Latency ({latency:.2f}s) at {url}")
                finding_type = "performance_anomaly"

            elif payload in response.text:
                 # Reflected input (potential XSS) - naive check
                 pass 

            if is_interesting:
                self._save_discovery(url, payload, param_name, status, response.text[:500], finding_type)

        except requests.exceptions.RequestException as e:
            print(f"[Fuzzer] Request failed: {e}")

    def _save_discovery(self, url, payload, param, status, sample_response, finding_type):
        """
        Saves interesting findings to the Hive Repository.
        """
        content = {
            "target_url": url,
            "parameter": param,
            "payload": payload,
            "status_code": status,
            "response_sample": sample_response
        }
        
        self.repo.save_finding(
            content=content,
            finding_type=finding_type,
            source="FuzzerTool",
            tags=["fuzzing", "security", str(status)]
        )