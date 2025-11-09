"""Test extraction from table formats."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from email_parser.utils import extract_ebitda

# Simulated OCR text from table
test_text = """
EBITDA Margin

C$1.5M C$3.6M C$1.4M C$925K

24.8% C$6.5M 30.3% C$4.3M
"""

print("Testing table extraction:")
print("="*80)
print("Text:")
print(test_text)
print("="*80)

result = extract_ebitda(test_text)
print(f"\nExtraction result: {result}")

if result:
    print(f"✅ Found: ${result[0]}M")
else:
    print("❌ Nothing found - need better pattern")

