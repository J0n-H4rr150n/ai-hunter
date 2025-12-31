"""
Tool Mapper - Maps runbook actions to actual tool implementations
Bridges the declarative runbook actions (strings) to imperative tool methods (callables)
"""

from typing import Dict, Any, Callable, Optional, TYPE_CHECKING
from datetime import datetime
import json

# Use TYPE_CHECKING to avoid circular imports and runtime dependency issues
if TYPE_CHECKING:
    from tools.som_browser import SoMBrowser
    from tools.tech_scanner import TechScanner
    from tools.fuzzer import Fuzzer
    from memory.finding_repository import FindingRepository
    from tools.findings_aggregator import FindingsAggregator
    from tools.report_generator import ReportGenerator


class ToolMapperError(Exception):
    """Raised when tool mapping or execution fails"""
    pass


class ToolMapper:
    """
    Maps runbook actions to tool implementations and handles execution.
    
    Responsibilities:
    - Maintain action -> tool method registry
    - Execute actions with appropriate tools
    - Handle parameter translation
    - Format results as findings dict
    - Provide error handling and logging
    """
    
    def __init__(self, browser: Optional[Any] = None, 
                 scanner: Optional[Any] = None,
                 fuzzer: Optional[Any] = None, 
                 repo: Optional[Any] = None,
                 aggregator: Optional[Any] = None,
                 report_gen: Optional[Any] = None):
        """
        Args:
            browser: SoMBrowser instance (optional, can be set later)
            scanner: TechScanner instance (optional)
            fuzzer: Fuzzer instance (optional)
            repo: FindingRepository instance (optional)
            aggregator: FindingsAggregator instance (optional)
            report_gen: ReportGenerator instance (optional)
        """
        self.browser = browser
        self.scanner = scanner
        self.fuzzer = fuzzer
        self.repo = repo
        self.aggregator = aggregator
        self.report_gen = report_gen
        
        # Build action mapping registry
        self.action_map = self._build_action_map()
        
        # Execution statistics
        self.stats = {
            'actions_executed': 0,
            'actions_succeeded': 0,
            'actions_failed': 0,
            'by_action': {}
        }
    
    def set_browser(self, browser: Any):
        """Set or update browser instance"""
        self.browser = browser
    
    def set_scanner(self, scanner: Any):
        """Set or update scanner instance"""
        self.scanner = scanner
    
    def set_fuzzer(self, fuzzer: Any):
        """Set or update fuzzer instance"""
        self.fuzzer = fuzzer
    
    def _build_action_map(self) -> Dict[str, Callable]:
        """Build the action → tool method mapping registry"""
        return {
            # Browser navigation actions
            'navigate': self._action_navigate,
            'click': self._action_click,
            'type': self._action_type,
            
            # Browser inspection actions
            'view_source': self._action_view_source,
            'inspect_dom': self._action_inspect_dom,
            'monitor_network': self._action_monitor_network,
            'capture_screenshot': self._action_capture_screenshot,
            'inspect_cookies': self._action_inspect_cookies,
            'inspect_storage': self._action_inspect_storage,
            'inspect_headers': self._action_inspect_headers,
            'parse_url': self._action_parse_url,
            'read_console': self._action_read_console,
            
            # Scanner actions
            'tech_scan': self._action_tech_scan,
            'fingerprint': self._action_fingerprint,
            'comprehensive_scan': self._action_comprehensive_scan,
            
            # Fuzzer actions
            'fuzz_parameter': self._action_fuzz_parameter,
            'run_intruder': self._action_run_intruder,
            
            # Analysis actions (use existing repo methods)
            'compile_findings': self._action_compile_findings,
            'pattern_search': self._action_pattern_search,
            'review_findings': self._action_review_findings,
            'extract_parameters': self._action_extract_parameters,
            
            # Testing actions
            'test_access': self._action_test_access,
            'test_manipulation': self._action_test_manipulation,
            
            # Reporting actions
            'compile_report': self._action_compile_report,
            'report_finding': self._action_report_finding,
            'generate_report': self._action_generate_report,
            
            # HITL actions
            'request_approval': self._action_request_approval,
            
            # Utility actions
            'conditional_check': self._action_conditional_check,
            'regex_validation': self._action_regex_validation,
        }
    
    def execute_action(self, action: str, step: dict, context: dict = None) -> Dict[str, Any]:
        """
        Execute a runbook action with the appropriate tool.
        
        Args:
            action: Action name from runbook step
            step: Full step definition from runbook
            context: Optional execution context (mission state, etc.)
        
        Returns:
            Dict of findings to be logged
        
        Raises:
            ToolMapperError: If action unknown or execution fails
        """
        
        self.stats['actions_executed'] += 1
        
        if action not in self.action_map:
            self.stats['actions_failed'] += 1
            raise ToolMapperError(f"Unknown action: {action}")
        
        # Track per-action stats
        if action not in self.stats['by_action']:
            self.stats['by_action'][action] = {'count': 0, 'successes': 0, 'failures': 0}
        
        self.stats['by_action'][action]['count'] += 1
        
        try:
            handler = self.action_map[action]
            findings = handler(step, context or {})
            
            # Add execution metadata
            findings['_step_id'] = step.get('id')
            findings['_step_name'] = step.get('name')
            findings['_action'] = action
            findings['_tool'] = step.get('tool', 'unknown')
            findings['_executed_at'] = datetime.utcnow().isoformat()
            findings['_success'] = True
            
            self.stats['actions_succeeded'] += 1
            self.stats['by_action'][action]['successes'] += 1
            
            return findings
            
        except Exception as e:
            self.stats['actions_failed'] += 1
            self.stats['by_action'][action]['failures'] += 1
            
            raise ToolMapperError(f"Action '{action}' failed: {e}")
    
    # ========================================================================
    # BROWSER NAVIGATION ACTIONS
    # ========================================================================
    
    def _action_navigate(self, step: dict, context: dict) -> Dict[str, Any]:
        """Navigate browser to URL"""
        if not self.browser:
            raise ToolMapperError("Browser not available for navigate action")
        
        url = step.get('url') or step.get('value') or context.get('target_url')
        if not url:
            raise ToolMapperError("No URL specified for navigate action")
        
        self.browser.navigate(url)
        
        return {
            'status': 'success',
            'url': url,
            'page_title': self.browser.page.title(),
            'current_url': self.browser.page.url
        }
    
    def _action_click(self, step: dict, context: dict) -> Dict[str, Any]:
        """Click an element"""
        if not self.browser:
            raise ToolMapperError("Browser not available for click action")
        
        element_id = step.get('element_id')
        if element_id is None:
            raise ToolMapperError("No element_id specified for click action")
        
        self.browser.click(element_id)
        
        return {
            'status': 'success',
            'element_id': element_id,
            'action': 'clicked'
        }
    
    def _action_type(self, step: dict, context: dict) -> Dict[str, Any]:
        """Type text into an element"""
        if not self.browser:
            raise ToolMapperError("Browser not available for type action")
        
        element_id = step.get('element_id')
        value = step.get('value')
        
        if element_id is None or value is None:
            raise ToolMapperError("element_id and value required for type action")
        
        self.browser.type_text(element_id, value)
        
        return {
            'status': 'success',
            'element_id': element_id,
            'text_length': len(value),
            'action': 'typed'
        }
    
    # ========================================================================
    # BROWSER INSPECTION ACTIONS
    # ========================================================================
    
    def _action_view_source(self, step: dict, context: dict) -> Dict[str, Any]:
        """Get raw HTML source"""
        if not self.browser:
            raise ToolMapperError("Browser not available")
        
        # Use page.content() which returns the HTML
        source = self.browser.page.content()
        
        # Extract key information from source
        findings = {
            'html_length': len(source),
            'has_script_tags': '<script' in source,
            'has_form_tags': '<form' in source,
            'has_input_tags': '<input' in source,
            'has_comments': '<!--' in source,
        }
        
        # Store full source in context for other steps to use
        if 'source_code' not in context:
            context['source_code'] = source
        
        return findings
    
    def _action_inspect_dom(self, step: dict, context: dict) -> Dict[str, Any]:
        """Inspect rendered DOM"""
        if not self.browser:
            raise ToolMapperError("Browser not available")
        
        dom = self.browser.page.content()
        
        return {
            'dom_length': len(dom),
            'dom_captured': True
        }
    
    def _action_monitor_network(self, step: dict, context: dict) -> Dict[str, Any]:
        """Capture network traffic"""
        if not self.browser:
            raise ToolMapperError("Browser not available")
        
        network_log = self.browser.network_logs
        
        # Analyze network requests
        unique_urls = set()
        api_endpoints = []
        methods = {}
        
        for entry in network_log:
            url = entry.get('url', '')
            method = entry.get('method', 'GET')
            
            unique_urls.add(url)
            methods[method] = methods.get(method, 0) + 1
            
            if '/api/' in url or url.endswith('.json'):
                api_endpoints.append(url)
        
        return {
            'total_requests': len(network_log),
            'unique_urls': len(unique_urls),
            'api_endpoints_discovered': len(api_endpoints),
            'methods_used': dict(methods),
            'all_unique_urls': list(unique_urls),
            'api_endpoints': api_endpoints
        }
    
    def _action_capture_screenshot(self, step: dict, context: dict) -> Dict[str, Any]:
        """Capture screenshot with Set-of-Marks"""
        if not self.browser:
            raise ToolMapperError("Browser not available")
        
        screenshot_bytes, elements = self.browser.inject_marks()
        
        return {
            'screenshot_captured': True,
            'screenshot_bytes': len(screenshot_bytes),
            'interactive_elements': len(elements),
            'elements_data': elements
        }
    
    def _action_inspect_cookies(self, step: dict, context: dict) -> Dict[str, Any]:
        """Inspect browser cookies"""
        if not self.browser:
            raise ToolMapperError("Browser not available")
        
        cookies = self.browser.context.cookies()
        
        cookie_analysis = {
            'total_cookies': len(cookies),
            'cookie_names': [c['name'] for c in cookies],
            'has_session_cookie': any('session' in c['name'].lower() for c in cookies),
            'has_auth_cookie': any('auth' in c['name'].lower() or 'token' in c['name'].lower() for c in cookies),
            'secure_cookies': sum(1 for c in cookies if c.get('secure', False)),
            'httponly_cookies': sum(1 for c in cookies if c.get('httpOnly', False)),
        }
        
        return cookie_analysis
    
    def _action_inspect_storage(self, step: dict, context: dict) -> Dict[str, Any]:
        """Inspect browser storage (localStorage, sessionStorage)"""
        if not self.browser:
            raise ToolMapperError("Browser not available")
        
        storage_type = step.get('storage_type', 'localStorage')
        
        try:
            if storage_type == 'localStorage':
                storage = self.browser.page.evaluate("() => JSON.stringify(window.localStorage)")
                storage = json.loads(storage) if storage else {}
            elif storage_type == 'sessionStorage':
                storage = self.browser.page.evaluate("() => JSON.stringify(window.sessionStorage)")
                storage = json.loads(storage) if storage else {}
            else:
                storage = {}
            
            return {
                'storage_type': storage_type,
                'item_count': len(storage) if storage else 0,
                'keys': list(storage.keys()) if storage else [],
                'has_sensitive_data': any(key.lower() in ['token', 'password', 'secret', 'key'] 
                                         for key in (storage.keys() if storage else []))
            }
        except Exception as e:
            return {
                'storage_type': storage_type,
                'error': str(e),
                'accessible': False
            }
    
    def _action_inspect_headers(self, step: dict, context: dict) -> Dict[str, Any]:
        """Inspect HTTP headers from network log"""
        if not self.browser:
            raise ToolMapperError("Browser not available")
        
        # Get first request from network log (usually the main page)
        network_log = self.browser.network_logs
        
        if not network_log:
            return {'headers_available': False}
        
        # Network logs don't capture response headers in our implementation
        # Return basic analysis
        return {
            'headers_available': True,
            'network_requests_analyzed': len(network_log),
            'note': 'Header inspection limited - network logs track URL/method/status only'
        }
    
    def _action_parse_url(self, step: dict, context: dict) -> Dict[str, Any]:
        """Parse URL parameters"""
        if not self.browser:
            raise ToolMapperError("Browser not available")
        
        from urllib.parse import urlparse, parse_qs
        
        current_url = self.browser.page.url
        parsed = urlparse(current_url)
        params = parse_qs(parsed.query)
        
        return {
            'url': current_url,
            'scheme': parsed.scheme,
            'domain': parsed.netloc,
            'path': parsed.path,
            'query_string': parsed.query,
            'parameters': {k: v[0] if len(v) == 1 else v for k, v in params.items()},
            'parameter_count': len(params),
            'has_id_params': any('id' in k.lower() for k in params.keys())
        }
    
    def _action_read_console(self, step: dict, context: dict) -> Dict[str, Any]:
        """Read browser console logs"""
        if not self.browser:
            raise ToolMapperError("Browser not available")
        
        # Playwright doesn't store console logs by default
        # Return placeholder indicating console monitoring not implemented
        return {
            'console_accessible': False,
            'note': 'Console log capture not implemented in current browser setup',
            'recommendation': 'Add console listener to SoMBrowser if needed'
        }
    
    # ========================================================================
    # SCANNER ACTIONS
    # ========================================================================
    
    def _action_tech_scan(self, step: dict, context: dict) -> Dict[str, Any]:
        """Run technology scanner"""
        if not self.scanner:
            return {'scanner_not_available': True, 'placeholder': True}
        
        url = context.get('target_url')
        report = self.scanner.comprehensive_scan(url)
        
        return {
            'server': report.get('server'),
            'frameworks': report.get('framework', []),
            'language': report.get('lang'),
            'technologies_detected': len(report.get('framework', [])),
            'full_report': report
        }
    
    def _action_fingerprint(self, step: dict, context: dict) -> Dict[str, Any]:
        """Fingerprint technology stack"""
        return self._action_tech_scan(step, context)
    
    def _action_comprehensive_scan(self, step: dict, context: dict) -> Dict[str, Any]:
        """Run comprehensive security scan"""
        return self._action_tech_scan(step, context)
    
    # ========================================================================
    # FUZZER ACTIONS
    # ========================================================================
    
    def _action_fuzz_parameter(self, step: dict, context: dict) -> Dict[str, Any]:
        """Fuzz a parameter"""
        if not self.fuzzer:
            return {'fuzzer_not_available': True, 'placeholder': True}
        
        # TODO: Implement actual fuzzing
        return {'fuzz_executed': True, 'placeholder': True}
    
    def _action_run_intruder(self, step: dict, context: dict) -> Dict[str, Any]:
        """Run intruder attack"""
        if not self.fuzzer:
            return {'fuzzer_not_available': True, 'placeholder': True}
        
        # TODO: Implement actual intruder
        return {'intruder_executed': True, 'placeholder': True}
    
    # ========================================================================
    # ANALYSIS ACTIONS
    # ========================================================================
    
    def _action_compile_findings(self, step: dict, context: dict) -> Dict[str, Any]:
        """Compile findings from repository"""
        if not self.repo:
            return {'repo_not_available': True, 'placeholder': True}
        
        mission_id = context.get('mission_id')
        findings = self.repo.search_findings(query="", limit=1000)
        
        return {
            'total_findings': len(findings),
            'findings_compiled': True,
            'mission_id': mission_id
        }
    
    def _action_pattern_search(self, step: dict, context: dict) -> Dict[str, Any]:
        """Search for patterns in findings"""
        patterns = step.get('patterns', [])
        
        return {
            'patterns_searched': len(patterns),
            'patterns': patterns,
            'matches_found': 0  # Placeholder
        }
    
    def _action_review_findings(self, step: dict, context: dict) -> Dict[str, Any]:
        """Review findings from previous steps"""
        return {'findings_reviewed': True, 'placeholder': True}
    
    def _action_extract_parameters(self, step: dict, context: dict) -> Dict[str, Any]:
        """Extract parameters from context"""
        return {'parameters_extracted': True, 'placeholder': True}
    
    # ========================================================================
    # TESTING ACTIONS
    # ========================================================================
    
    def _action_test_access(self, step: dict, context: dict) -> Dict[str, Any]:
        """Test access to resources"""
        return {'access_tested': True, 'placeholder': True}
    
    def _action_test_manipulation(self, step: dict, context: dict) -> Dict[str, Any]:
        """Test parameter manipulation"""
        return {'manipulation_tested': True, 'placeholder': True}
    
    # ========================================================================
    # REPORTING ACTIONS
    # ========================================================================
    
    def _action_compile_report(self, step: dict, context: dict) -> Dict[str, Any]:
        """Compile report from findings"""
        return {'report_compiled': True, 'placeholder': True}
    
    def _action_report_finding(self, step: dict, context: dict) -> Dict[str, Any]:
        """Report a specific finding"""
        value = step.get('value', 'Finding')
        evidence = step.get('evidence', '')
        
        return {
            'finding_reported': True,
            'finding_value': value,
            'evidence': evidence
        }
    
    # ========================================================================
    # AGGREGATION & REPORTING ACTIONS
    # ========================================================================
    
    async def _action_compile_findings(self, step: dict, context: dict) -> Dict[str, Any]:
        """Compile findings using FindingsAggregator"""
        if not self.aggregator:
            return {
                'error': 'FindingsAggregator not available',
                'status': 'skipped'
            }
        
        mission_id = context.get('mission_id', 1)
        finding_types = step.get('finding_types')
        limit = step.get('limit', 100)
        
        try:
            compiled = await self.aggregator.compile_findings(
                mission_id=mission_id,
                finding_types=finding_types,
                limit=limit
            )
            return compiled
        except Exception as e:
            return {
                'error': f'Failed to compile findings: {str(e)}',
                'status': 'error'
            }
    
    async def _action_pattern_search(self, step: dict, context: dict) -> Dict[str, Any]:
        """Search findings for patterns"""
        if not self.aggregator:
            return {
                'error': 'FindingsAggregator not available',
                'status': 'skipped'
            }
        
        mission_id = context.get('mission_id', 1)
        pattern = step.get('pattern', '')
        field = step.get('field', 'description')
        limit = step.get('limit', 50)
        
        try:
            results = await self.aggregator.pattern_search(
                mission_id=mission_id,
                pattern=pattern,
                field=field,
                limit=limit
            )
            return {
                'pattern': pattern,
                'field': field,
                'matches_found': len(results),
                'results': results
            }
        except Exception as e:
            return {
                'error': f'Pattern search failed: {str(e)}',
                'status': 'error'
            }
    
    async def _action_review_findings(self, step: dict, context: dict) -> Dict[str, Any]:
        """Review and summarize findings"""
        if not self.aggregator:
            return {
                'error': 'FindingsAggregator not available',
                'status': 'skipped'
            }
        
        mission_id = context.get('mission_id', 1)
        finding_ids = step.get('finding_ids')
        
        try:
            review = await self.aggregator.review_findings(
                mission_id=mission_id,
                finding_ids=finding_ids
            )
            return review
        except Exception as e:
            return {
                'error': f'Review failed: {str(e)}',
                'status': 'error'
            }
    
    def _action_generate_report(self, step: dict, context: dict) -> Dict[str, Any]:
        """Generate a report using ReportGenerator"""
        if not self.report_gen:
            return {
                'error': 'ReportGenerator not available',
                'status': 'skipped'
            }
        
        mission_id = context.get('mission_id', 1)
        report_type = step.get('report_type', 'executive_summary')
        findings = context.get('findings', [])
        metadata = context.get('mission_metadata', {})
        
        try:
            if report_type == 'executive_summary':
                report = self.report_gen.generate_executive_summary(
                    mission_id=mission_id,
                    findings=findings,
                    mission_metadata=metadata
                )
            elif report_type == 'technical':
                report = self.report_gen.generate_technical_report(
                    mission_id=mission_id,
                    findings=findings,
                    mission_metadata=metadata
                )
            elif report_type == 'vulnerability':
                focus_types = step.get('focus_types')
                report = self.report_gen.generate_vulnerability_report(
                    mission_id=mission_id,
                    findings=findings,
                    focus_types=focus_types
                )
            elif report_type == 'technology_inventory':
                report = self.report_gen.generate_technology_inventory(
                    mission_id=mission_id,
                    findings=findings
                )
            else:
                return {
                    'error': f'Unknown report type: {report_type}',
                    'status': 'error'
                }
            
            return {
                'report_type': report_type,
                'report_generated': True,
                'report': report,
                'report_length': len(report)
            }
        except Exception as e:
            return {
                'error': f'Report generation failed: {str(e)}',
                'status': 'error'
            }
    
    # ========================================================================
    # HITL ACTIONS
    # ========================================================================
    
    def _action_request_approval(self, step: dict, context: dict) -> Dict[str, Any]:
        """Request human approval"""
        return {
            'approval_requested': True,
            'approval_type': 'hitl_checkpoint',
            'awaiting_response': True
        }
    
    # ========================================================================
    # UTILITY ACTIONS
    # ========================================================================
    
    def _action_conditional_check(self, step: dict, context: dict) -> Dict[str, Any]:
        """Perform conditional check"""
        condition = step.get('condition', '')
        
        return {
            'condition': condition,
            'condition_met': False,  # Placeholder
            'check_performed': True
        }
    
    def _action_regex_validation(self, step: dict, context: dict) -> Dict[str, Any]:
        """Validate with regex"""
        validation_rules = step.get('validation_rules', [])
        
        return {
            'validation_rules': validation_rules,
            'rules_checked': len(validation_rules),
            'valid': False  # Placeholder
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get execution statistics"""
        return self.stats.copy()
