"""Debug OCR extraction to see what text is being returned."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytesseract
import shutil
from pdf2image import convert_from_bytes
from PIL import Image

from email_parser.ner_body_parser import NERBodyParser

# Configure tesseract
tesseract_path = shutil.which('tesseract')
if tesseract_path:
    pytesseract.pytesseract.tesseract_cmd = tesseract_path
    print(f"✓ Using tesseract at: {tesseract_path}\n")

WORKSPACE = Path(__file__).parent.parent
SAMPLE_EMAILS_DIR = WORKSPACE / "sample_emails"

# Test email with PDF
TEST_EMAIL = "FW Project Gravy - Franchise QSR Portfolio Acquisition Opportunity.msg"


def main():
    """Debug OCR extraction."""
    print("="*100)
    print("🔍 OCR Extraction Debug")
    print("="*100)
    
    email_path = SAMPLE_EMAILS_DIR / TEST_EMAIL
    
    if not email_path.exists():
        print(f"❌ Email not found: {TEST_EMAIL}")
        return
    
    # Extract email
    parser = NERBodyParser()
    email_data = parser.extract_msg_file(email_path)
    
    print(f"\n📧 Email: {TEST_EMAIL}")
    print(f"📎 Attachments: {len(email_data.attachments)}\n")
    
    # Process each PDF attachment
    for att in email_data.attachments:
        filename_lower = att.filename.lower()
        
        if not filename_lower.endswith('.pdf'):
            print(f"⏭️  Skipping non-PDF: {att.filename}")
            continue
        
        print("="*100)
        print(f"📄 Processing: {att.filename} ({att.size_bytes / 1024:.1f} KB)")
        print("="*100)
        
        try:
            # Convert PDF to images
            print("\n🖼️  Converting PDF to images...")
            images = convert_from_bytes(att.content, dpi=200)
            print(f"✓ Converted to {len(images)} image(s)")
            
            # OCR each page
            for page_num, image in enumerate(images[:3]):  # First 3 pages
                print(f"\n--- Page {page_num + 1} ---")
                print(f"Image size: {image.size}")
                
                # Extract text with OCR
                text = pytesseract.image_to_string(image)
                
                print(f"\n📝 OCR Extracted Text ({len(text)} chars):")
                print("-"*100)
                
                if text.strip():
                    # Show first 1000 chars
                    print(text[:1000])
                    if len(text) > 1000:
                        print(f"\n... [truncated, {len(text) - 1000} more chars]")
                else:
                    print("⚠️  NO TEXT EXTRACTED!")
                
                # Try to find EBITDA in OCR text
                import re
                ebitda_patterns = [
                    r'\$\s*(\d+\.?\d*)\s*M',
                    r'EBITDA[:\s]+\$\s*(\d+\.?\d*)',
                    r'(\d+\.?\d*)\s*million',
                ]
                
                found_ebitda = []
                for pattern in ebitda_patterns:
                    matches = re.findall(pattern, text, re.IGNORECASE)
                    if matches:
                        found_ebitda.extend(matches)
                
                if found_ebitda:
                    print(f"\n💰 EBITDA values found in OCR text: {found_ebitda}")
                else:
                    print(f"\n⚠️  No EBITDA patterns found in OCR text")
                
                print("\n" + "="*100)
                
        except Exception as e:
            print(f"\n❌ Error processing PDF: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()

