"""Debug what text OCR + NER actually receives."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytesseract
import shutil
from pdf2image import convert_from_bytes

from email_parser.ner_body_parser import NERBodyParser
from email_parser.utils import extract_ebitda

# Configure tesseract
tesseract_path = shutil.which('tesseract')
if tesseract_path:
    pytesseract.pytesseract.tesseract_cmd = tesseract_path

WORKSPACE = Path(__file__).parent.parent
SAMPLE_EMAILS_DIR = WORKSPACE / "sample_emails"
TEST_EMAIL = "FW Project Gravy - Franchise QSR Portfolio Acquisition Opportunity.msg"


def main():
    """Debug OCR text extraction."""
    print("="*100)
    print("🔍 Debug: What does OCR + NER receive?")
    print("="*100)
    
    email_path = SAMPLE_EMAILS_DIR / TEST_EMAIL
    
    # Get email data
    parser = NERBodyParser()
    email_data = parser.extract_msg_file(email_path)
    
    print(f"\n📧 Email: {TEST_EMAIL}")
    print(f"📎 Attachments: {len(email_data.attachments)}\n")
    
    # Process PDF
    for att in email_data.attachments:
        if not att.filename.lower().endswith('.pdf'):
            continue
        
        print("="*100)
        print(f"📄 {att.filename}")
        print("="*100)
        
        # Convert and OCR
        images = convert_from_bytes(att.content, dpi=200)
        print(f"✓ Converted to {len(images)} images\n")
        
        all_text = []
        
        for page_num, image in enumerate(images[:3]):
            text = pytesseract.image_to_string(image)
            all_text.append(text)
            
            print(f"--- Page {page_num + 1} ({len(text)} chars) ---")
            
            # Show lines containing "EBITDA"
            ebitda_lines = [line for line in text.split('\n') if 'EBITDA' in line.upper()]
            
            if ebitda_lines:
                print("📊 Lines containing 'EBITDA':")
                for line in ebitda_lines:
                    print(f"  → {line.strip()}")
                    
                    # Try to extract from each line
                    result = extract_ebitda(line)
                    if result:
                        print(f"     ✅ Extracted: ${result[0]}M from '{result[1]}'")
                    else:
                        print(f"     ❌ No extraction")
            else:
                print("⚠️  No lines containing 'EBITDA'")
            
            print()
        
        # Combine all text
        combined_text = "\n\n".join(all_text)
        
        print("="*100)
        print("🔍 Testing extraction on combined OCR text:")
        print("="*100)
        
        result = extract_ebitda(combined_text)
        if result:
            print(f"✅ SUCCESS: Extracted ${result[0]}M")
            print(f"   Raw text: '{result[1]}'")
        else:
            print("❌ FAILED: No EBITDA extracted from combined text")
            print("\nFirst 500 chars of combined text:")
            print("-"*100)
            print(combined_text[:500])


if __name__ == "__main__":
    main()

