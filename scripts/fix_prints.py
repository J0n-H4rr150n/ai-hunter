#!/usr/bin/env python3
"""Script to replace all print statements containing [Auto] with self.log_to_ui()"""

import re
from pathlib import Path

def fix_prints(filepath):
    """Replace print statements with log_to_ui"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Pattern to match print statements with [Auto]
    # Handles both single and double quotes, with or without f-string
    patterns = [
        (r'print\(f"([^"]*\[Auto\][^"]*)"\)', r'self.log_to_ui(f"\1")'),
        (r"print\(f'([^']*\[Auto\][^']*)'\)", r"self.log_to_ui(f'\1')"),
        (r'print\("([^"]*\[Auto\][^"]*)"\)', r'self.log_to_ui("\1")'),
        (r"print\('([^']*\[Auto\][^']*)'\)", r"self.log_to_ui('\1')"),
    ]
    
    original_content = content
    for pattern, replacement in patterns:
        content = re.sub(pattern, replacement, content)
    
    if content != original_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ Fixed {filepath}")
        return True
    else:
        print(f"ℹ️  No changes needed in {filepath}")
        return False

if __name__ == "__main__":
    filepath = Path(__file__).parent.parent / "core" / "autonomous_loop.py"
    fix_prints(filepath)
