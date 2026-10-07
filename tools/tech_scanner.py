import requests
from config.safety import SAFETY_LIMITS
import re
from config.config import Config

class TechScanner:
    """
    Identifies technologies used by a target web application.
    Analyzes HTTP headers, cookies, and HTML content to fingerprint the stack.
    Integrates with QuotaManager and FindingRepository.
    """

    # Dictionary of simple signatures to look for
    SIGNATURES = {
        "headers": {
            "Server": "Web Server",
            "X-Powered-By": "Framework/Language",
            "X-AspNet-Version": "ASP.NET",
            "X-Generator": "CMS",
            "Via": "Proxy/Load Balancer"
        },
        "cookies": {
            "PHPSESSID": "PHP",
            "JSESSIONID": "Java/Tomcat",
            "csrftoken": "Django",
            "laravel_session": "Laravel",
            "ci_session": "CodeIgniter",
            "connect.sid": "Node.js/Express"
        },
        "meta": {
            r'<meta name="generator" content="WordPress': "WordPress",
            r'<meta name="generator" content="Drupal': "Drupal",
            r'<meta name="generator" content="Joomla': "Joomla",
            r'<div id="__next">': "Next.js",
            r'react-root': "React"
        }
    }

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
            'User-Agent': 'HiveMindAgent-Scanner/1.0'
        })

    def scan_url(self, url: str):
        """
        Performs a fingerprint scan on the target URL.
        """
        print(f"[Scanner] Analyzing technology stack for: {url}")
        
        if not self.quota.check_limit("actions"):
            print("[Scanner] 🛑 Quota exceeded. Aborting scan.")
            return

        try:
            # Tally cost
            self.quota.tally("actions", 1)
            
            response = self.session.get(url, timeout=SAFETY_LIMITS['FUZZER_TIMEOUT'])
            technologies = self._fingerprint(response)
            
            if technologies:
                print(f"[Scanner] 🔍 Identified: {technologies}")
                self._save_results(url, technologies)
                return technologies
            else:
                print("[Scanner] No specific technologies identified.")
                return None

        except requests.exceptions.RequestException as e:
            print(f"[Scanner] Scan failed: {e}")
            return None

    def _fingerprint(self, response):
        """
        Internal method to match response data against signatures.
        """
        techs = {}

        # 1. Header Analysis
        for header, category in self.SIGNATURES["headers"].items():
            value = response.headers.get(header)
            if value:
                # Store as "Web Server: Nginx/1.18"
                techs[category] = value

        # 2. Cookie Analysis
        for cookie in response.cookies:
            for key, tech_name in self.SIGNATURES["cookies"].items():
                if key in cookie.name:
                    techs[f"Framework (Cookie: {key})"] = tech_name

        # 3. HTML Content Analysis (Regex)
        text = response.text
        for pattern, tech_name in self.SIGNATURES["meta"].items():
            if re.search(pattern, text, re.IGNORECASE):
                techs["Frontend/CMS"] = tech_name

        return techs

    def _save_results(self, url, techs):
        """
        Saves the identified tech stack to the Hive.
        """
        content = {
            "url": url,
            "technologies": techs
        }
        
        # Create tags based on keys (e.g., "WordPress", "PHP") for easy search later
        tags = ["recon", "technology"]
        for k, v in techs.items():
            tags.append(str(v).split('/')[0]) # Add simple tag like "Nginx" or "PHP"

        self.repo.save_finding(
            content=content,
            finding_type="tech_fingerprint",
            source="TechScanner",
            tags=tags
        )