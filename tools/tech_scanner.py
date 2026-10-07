import logging
import re
import socket
import ssl
import subprocess
from datetime import datetime, timezone
from urllib.parse import urlparse
import requests
from config.safety import SAFETY_LIMITS
import re
from config.config import Config

logger = logging.getLogger(__name__)


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


    def inspect_tls(self, url: str):
        """
        Record the target's certificate.

        Verification is disabled for targets (see Config.VERIFY_TLS) because an
        expired or self-signed certificate is a finding, not a reason to refuse to
        connect. That only holds if the certificate is actually examined, which is
        what this does: fetch it without validating, then report what is wrong with
        it rather than letting the problem pass unnoticed.
        """
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return None

        host = parsed.hostname
        port = parsed.port or 443
        if not host:
            return None

        # An unverified context still returns the peer certificate, which is the
        # only way to inspect a chain the platform would otherwise reject.
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        try:
            with socket.create_connection((host, port), timeout=SAFETY_LIMITS["FUZZER_TIMEOUT"]) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as tls:
                    der = tls.getpeercert(binary_form=True)
                    cert = tls.getpeercert()
                    protocol = tls.version()
        except Exception as e:
            logger.warning("TLS inspection failed for %s: %s", url, e)
            return None

        info = _decode_certificate(der, cert)
        info.update({"url": url, "host": host, "port": port, "tls_version": protocol})

        # Does the certificate actually cover the name we asked for?
        names = info.get("sans") or ([info["subject_cn"]] if info.get("subject_cn") else [])
        info["hostname_matches"] = _host_matches(host, names)

        issues = []
        if info.get("expired"):
            issues.append(f"expired {abs(info['days_remaining'])} days ago")
        elif info.get("days_remaining") is not None and info["days_remaining"] <= 30:
            issues.append(f"expires in {info['days_remaining']} days")
        if info.get("self_signed"):
            issues.append("self-signed")
        if info["hostname_matches"] is False:
            issues.append(f"hostname mismatch (cert covers {', '.join(names[:4]) or 'nothing'})")
        info["issues"] = issues

        self.repo.save_finding(
            content=info,
            finding_type="tls_certificate",
            source="TechScanner",
            tags=["recon", "tls"] + (["insecure"] if issues else ["valid"]),
        )

        if issues:
            print(f"[Scanner] 🔒 TLS issues on {host}: {'; '.join(issues)}")
        return info

    def scan_url(self, url: str):
        """
        Performs a fingerprint scan on the target URL.
        """
        print(f"[Scanner] Analyzing technology stack for: {url}")
        
        if not self.quota.check_limit("actions"):
            print("[Scanner] 🛑 Quota exceeded. Aborting scan.")
            return

        # Certificate first: if TLS is broken that is itself worth reporting.
        self.inspect_tls(url)

        try:
            # Tally cost
            self.quota.tally("actions", 1)
            
            response = self.session.get(url, timeout=SAFETY_LIMITS['FUZZER_TIMEOUT'], verify=Config.requests_verify())
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


def _host_matches(host: str, names) -> bool:
    """RFC 6125 style check, including a single leading wildcard label."""
    host = (host or "").lower().rstrip(".")
    for name in names or []:
        name = str(name).lower().rstrip(".")
        if name == host:
            return True
        if name.startswith("*."):
            # A wildcard covers exactly one label, so a.b.example != *.example
            if host.split(".", 1)[-1] == name[2:] and host.count(".") == name.count("."):
                return True
    return False


def _decode_certificate(der: bytes, cert: dict) -> dict:
    """
    Pull the interesting fields out of a certificate.

    getpeercert() returns {} on an unverified connection, so the DER is parsed
    directly via openssl, which is already a dependency of the lab workflow.
    """
    info = {"subject_cn": None, "issuer_cn": None, "sans": [],
            "not_before": None, "not_after": None, "days_remaining": None,
            "expired": None, "self_signed": None}

    text = None
    try:
        proc = subprocess.run(
            ["openssl", "x509", "-inform", "DER", "-noout",
             "-subject", "-issuer", "-dates", "-ext", "subjectAltName"],
            input=der, capture_output=True, timeout=10,
        )
        text = proc.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("could not decode certificate: %s", e)

    if text:
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("subject="):
                info["subject"] = line[8:].strip()
                m = re.search(r"CN\s*=\s*([^,/]+)", line)
                if m:
                    info["subject_cn"] = m.group(1).strip()
            elif line.startswith("issuer="):
                info["issuer"] = line[7:].strip()
                m = re.search(r"CN\s*=\s*([^,/]+)", line)
                if m:
                    info["issuer_cn"] = m.group(1).strip()
            elif line.startswith("notBefore="):
                info["not_before"] = line[10:].strip()
            elif line.startswith("notAfter="):
                info["not_after"] = line[9:].strip()
            elif line.startswith("DNS:"):
                info["sans"] = [p.strip()[4:] for p in line.split(",") if p.strip().startswith("DNS:")]

    if info.get("not_after"):
        try:
            expiry = datetime.strptime(info["not_after"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            info["days_remaining"] = (expiry - datetime.now(timezone.utc)).days
            info["expired"] = info["days_remaining"] < 0
        except ValueError as e:
            logger.debug("unparsed notAfter %r: %s", info["not_after"], e)

    if info.get("subject") and info.get("issuer"):
        info["self_signed"] = info["subject"] == info["issuer"]

    return info
