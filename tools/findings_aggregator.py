"""
FindingsAggregator - High-level analysis tool for runbook findings.

This tool wraps FindingRepository with analysis methods that runbooks can invoke.
It provides pattern matching, similarity search, and finding compilation.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

# Type hints only - no runtime import
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from memory.finding_repository import FindingRepository


class FindingsAggregator:
    """
    High-level analysis tool for aggregating and analyzing findings.
    
    This class provides runbook-friendly methods for:
    - Compiling findings from multiple sources
    - Pattern matching across findings
    - Similarity search using pgvector
    - Statistical analysis of findings
    """
    
    def __init__(self, finding_repository: "FindingRepository"):
        """
        Initialize the FindingsAggregator.
        
        Args:
            finding_repository: Instance of FindingRepository for storage/retrieval
        """
        self.repo = finding_repository
    
    async def compile_findings(
        self,
        mission_id: int,
        finding_types: Optional[List[str]] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Compile all findings for a mission, optionally filtered by type.
        
        Args:
            mission_id: Mission to compile findings for
            finding_types: Optional list of finding types to filter (e.g., ['tech_fingerprint', 'vulnerability'])
            limit: Maximum number of findings to retrieve
            
        Returns:
            Dict with compiled findings and statistics:
            {
                'total': int,
                'by_type': Dict[str, int],
                'by_severity': Dict[str, int],
                'findings': List[Dict],
                'compiled_at': str
            }
        """
        # Get all findings for mission
        all_findings = await self.repo.get_findings_by_mission(mission_id, limit=limit)
        
        # Filter by type if specified
        if finding_types:
            findings = [f for f in all_findings if f.get('finding_type') in finding_types]
        else:
            findings = all_findings
        
        # Calculate statistics
        by_type: Dict[str, int] = {}
        by_severity: Dict[str, int] = {}
        
        for finding in findings:
            # Count by type
            finding_type = finding.get('finding_type', 'unknown')
            by_type[finding_type] = by_type.get(finding_type, 0) + 1
            
            # Count by severity
            severity = finding.get('severity', 'info')
            by_severity[severity] = by_severity.get(severity, 0) + 1
        
        return {
            'total': len(findings),
            'by_type': by_type,
            'by_severity': by_severity,
            'findings': findings,
            'compiled_at': datetime.now(timezone.utc).isoformat()
        }
    
    async def pattern_search(
        self,
        mission_id: int,
        pattern: str,
        field: str = 'description',
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Search findings for a text pattern in a specific field.
        
        Args:
            mission_id: Mission to search within
            pattern: Text pattern to search for (case-insensitive substring match)
            field: Field to search in ('title', 'description', 'details', 'raw_data')
            limit: Maximum results to return
            
        Returns:
            List of findings matching the pattern
        """
        all_findings = await self.repo.get_findings_by_mission(mission_id, limit=limit * 2)
        
        # Filter by pattern
        matching_findings = []
        for finding in all_findings:
            field_value = finding.get(field, '')
            if isinstance(field_value, str) and pattern.lower() in field_value.lower():
                matching_findings.append(finding)
            elif isinstance(field_value, dict):
                # Search in dict values (for 'details' field)
                if self._search_dict(field_value, pattern):
                    matching_findings.append(finding)
            
            if len(matching_findings) >= limit:
                break
        
        return matching_findings
    
    def _search_dict(self, data: Dict, pattern: str) -> bool:
        """Recursively search dict for pattern."""
        pattern_lower = pattern.lower()
        for key, value in data.items():
            if isinstance(value, str) and pattern_lower in value.lower():
                return True
            elif isinstance(value, dict):
                if self._search_dict(value, pattern):
                    return True
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and pattern_lower in item.lower():
                        return True
                    elif isinstance(item, dict):
                        if self._search_dict(item, pattern):
                            return True
        return False
    
    async def similarity_search(
        self,
        mission_id: int,
        query_text: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Find findings similar to query text using vector embeddings.
        
        Args:
            mission_id: Mission to search within
            query_text: Text to find similar findings for
            limit: Maximum results to return
            
        Returns:
            List of findings similar to query_text, ordered by similarity
        """
        # Use FindingRepository's similarity search
        similar_findings = await self.repo.search_similar_findings(
            query_text=query_text,
            mission_id=mission_id,
            limit=limit
        )
        return similar_findings
    
    async def get_high_value_findings(
        self,
        mission_id: int,
        min_severity: str = 'medium',
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get high-value findings (high severity, vulnerabilities, credentials).
        
        Args:
            mission_id: Mission to search within
            min_severity: Minimum severity ('critical', 'high', 'medium')
            limit: Maximum results
            
        Returns:
            List of high-value findings
        """
        severity_rank = {'critical': 4, 'high': 3, 'medium': 2, 'low': 1, 'info': 0}
        min_rank = severity_rank.get(min_severity.lower(), 2)
        
        all_findings = await self.repo.get_findings_by_mission(mission_id, limit=limit * 2)
        
        high_value = []
        for finding in all_findings:
            severity = finding.get('severity', 'info').lower()
            finding_type = finding.get('finding_type', '').lower()
            
            # Check severity
            if severity_rank.get(severity, 0) >= min_rank:
                high_value.append(finding)
            # Or check for high-value types
            elif any(keyword in finding_type for keyword in ['vulnerability', 'credential', 'secret', 'key', 'password']):
                high_value.append(finding)
            
            if len(high_value) >= limit:
                break
        
        return high_value
    
    async def review_findings(
        self,
        mission_id: int,
        finding_ids: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """
        Review and summarize specific findings or all mission findings.
        
        Args:
            mission_id: Mission to review
            finding_ids: Optional list of specific finding IDs to review
            
        Returns:
            Dict with review summary:
            {
                'reviewed_count': int,
                'summary': str,
                'key_findings': List[Dict],
                'recommendations': List[str]
            }
        """
        if finding_ids:
            # Get specific findings
            findings = []
            for fid in finding_ids:
                finding = await self.repo.get_finding_by_id(fid)
                if finding and finding.get('mission_id') == mission_id:
                    findings.append(finding)
        else:
            # Get all mission findings
            findings = await self.repo.get_findings_by_mission(mission_id, limit=1000)
        
        # Analyze findings
        key_findings = []
        vulnerabilities = 0
        techs = set()
        
        for finding in findings:
            severity = finding.get('severity', 'info').lower()
            finding_type = finding.get('finding_type', '').lower()
            
            # Track vulnerabilities
            if 'vulnerability' in finding_type or severity in ['critical', 'high']:
                vulnerabilities += 1
                key_findings.append({
                    'id': finding.get('id'),
                    'type': finding.get('finding_type'),
                    'title': finding.get('title'),
                    'severity': severity
                })
            
            # Track technologies
            if 'tech' in finding_type or 'fingerprint' in finding_type:
                details = finding.get('details', {})
                if isinstance(details, dict):
                    tech_name = details.get('technology') or details.get('name')
                    if tech_name:
                        techs.add(tech_name)
        
        # Generate summary
        summary_lines = [
            f"Reviewed {len(findings)} findings for mission {mission_id}",
            f"Found {vulnerabilities} potential vulnerabilities",
            f"Identified {len(techs)} technologies"
        ]
        
        # Generate recommendations
        recommendations = []
        if vulnerabilities > 0:
            recommendations.append(f"Investigate {vulnerabilities} potential vulnerabilities")
        if len(techs) > 5:
            recommendations.append(f"Comprehensive tech stack detected ({len(techs)} technologies) - consider targeted scanning")
        if len(findings) > 100:
            recommendations.append("Large finding set - consider filtering by severity or type")
        
        return {
            'reviewed_count': len(findings),
            'summary': '\n'.join(summary_lines),
            'key_findings': key_findings[:10],  # Top 10
            'recommendations': recommendations
        }
    
    async def deduplicate_findings(
        self,
        mission_id: int,
        similarity_threshold: float = 0.9
    ) -> Dict[str, Any]:
        """
        Identify and report duplicate findings using vector similarity.
        
        Args:
            mission_id: Mission to deduplicate
            similarity_threshold: Cosine similarity threshold (0.0-1.0)
            
        Returns:
            Dict with deduplication results:
            {
                'total_findings': int,
                'unique_findings': int,
                'duplicates_found': int,
                'duplicate_groups': List[List[int]]  # Groups of duplicate finding IDs
            }
        """
        all_findings = await self.repo.get_findings_by_mission(mission_id, limit=1000)
        
        # This is a simplified implementation
        # In production, you'd use pgvector's similarity functions
        seen = set()
        duplicates = []
        duplicate_groups = []
        
        for i, finding in enumerate(all_findings):
            finding_id = finding.get('id')
            title = finding.get('title', '')
            description = finding.get('description', '')
            
            # Simple text-based deduplication
            key = f"{title}:{description}"
            if key in seen:
                duplicates.append(finding_id)
                # Find the group this belongs to
                found = False
                for group in duplicate_groups:
                    if any(all_findings[j].get('title') == title for j in range(len(all_findings)) if all_findings[j].get('id') in group):
                        group.append(finding_id)
                        found = True
                        break
                if not found:
                    # Create new group
                    duplicate_groups.append([finding_id])
            else:
                seen.add(key)
        
        return {
            'total_findings': len(all_findings),
            'unique_findings': len(seen),
            'duplicates_found': len(duplicates),
            'duplicate_groups': duplicate_groups
        }
