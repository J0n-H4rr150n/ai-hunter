"""
Hive bucket manager for structured file storage
GCS-compatible Hive partitioning scheme
"""

import os
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from config.config import Config

class HiveBucket:
    """Manages structured file storage with Hive partitioning"""
    
    def __init__(self, base_path: Optional[str] = None):
        self.base_path = Path(base_path or Config.HIVE_BUCKET_ROOT)
        self._ensure_structure()
    
    def _ensure_structure(self):
        """Create base directories"""
        dirs = [
            'screenshots',
            'tool_outputs',
            'network_logs',
            'raw_json',
            'dom_snapshots'
        ]
        for d in dirs:
            (self.base_path / d).mkdir(parents=True, exist_ok=True)
    
    def _get_partition_path(self, artifact_type: str, mission_id: int, tool_name: Optional[str] = None) -> Path:
        """
        Generate Hive-style partition path
        Format: artifact_type/mission_id=<id>/[tool=<tool>/]timestamp=<YYYY-MM-DD-HH>/
        """
        now = datetime.now(timezone.utc)
        timestamp_part = now.strftime("%Y-%m-%d-%H")
        
        parts = [
            self.base_path,
            artifact_type,
            f"mission_id={mission_id}"
        ]
        
        if tool_name:
            parts.append(f"tool={tool_name}")
        
        parts.append(f"timestamp={timestamp_part}")
        
        path = Path(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def save_screenshot(self, mission_id: int, screenshot_bytes: bytes, action: str) -> str:
        """Save screenshot to hive bucket"""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"{action}_{timestamp}.jpg"
        
        partition_path = self._get_partition_path('screenshots', mission_id)
        file_path = partition_path / filename
        
        with open(file_path, 'wb') as f:
            f.write(screenshot_bytes)
        
        # Return relative path from base
        return str(file_path.relative_to(self.base_path))
    
    def save_tool_output(self, mission_id: int, tool_name: str, output_data: dict) -> str:
        """Save tool output to hive bucket"""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"{tool_name}_{timestamp}.json"
        
        partition_path = self._get_partition_path('tool_outputs', mission_id, tool_name)
        file_path = partition_path / filename
        
        with open(file_path, 'w') as f:
            json.dump(output_data, f, indent=2)
        
        return str(file_path.relative_to(self.base_path))
    
    def save_network_log(self, mission_id: int, direction: str, data: dict) -> str:
        """Save network request/response to hive bucket"""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"{direction}_{timestamp}.json"
        
        partition_path = self._get_partition_path('network_logs', mission_id)
        file_path = partition_path / filename
        
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        return str(file_path.relative_to(self.base_path))
    
    def save_raw_json(self, mission_id: int, data_type: str, data: dict) -> str:
        """Save raw JSON data (plans, thoughts, etc.)"""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"{data_type}_{timestamp}.json"
        
        partition_path = self._get_partition_path('raw_json', mission_id)
        file_path = partition_path / filename
        
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        return str(file_path.relative_to(self.base_path))
    
    def save_dom_snapshot(self, mission_id: int, html_content: str) -> str:
        """Save DOM snapshot"""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"snapshot_{timestamp}.html"
        
        partition_path = self._get_partition_path('dom_snapshots', mission_id)
        file_path = partition_path / filename
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return str(file_path.relative_to(self.base_path))
    
    def get_absolute_path(self, relative_path: str) -> Path:
        """Convert relative path to absolute"""
        return self.base_path / relative_path
    
    def list_mission_artifacts(self, mission_id: int, artifact_type: Optional[str] = None) -> list:
        """List all artifacts for a mission"""
        if artifact_type:
            search_base = self.base_path / artifact_type / f"mission_id={mission_id}"
        else:
            search_base = self.base_path
        
        if not search_base.exists():
            return []
        
        artifacts = []
        for file_path in search_base.rglob('*'):
            if file_path.is_file():
                artifacts.append({
                    'path': str(file_path.relative_to(self.base_path)),
                    'absolute_path': str(file_path),
                    'size': file_path.stat().st_size,
                    'modified': datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
                })
        
        return artifacts
