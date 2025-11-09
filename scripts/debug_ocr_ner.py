"""Debug OCR + NER parser specifically."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from email_parser.ocr_ner_parser import OCRNERParser

WORKSPACE = Path(__file__).parent.parent
SAMPLE_EMAILS_DIR = WORKSPACE / "sample_emails"

TEST_EMAIL = "FW Project Gravy - Franchise QSR Portfolio Acquisition Opportunity.msg"


def main():
    """Debug OCR + NER parser."""
    print("="*100)
    print("🔍 Debugging OCR + NER Parser")
    print("="*100)
    
    email_path = SAMPLE_EMAILS_DIR / TEST_EMAIL
    
    if not email_path.exists():
        print(f"❌ Email not found")
        return
    
    print(f"\n📧 Testing: {TEST_EMAIL}\n")
    
    try:
        parser = OCRNERParser()
        
        print("✓ Parser initialized\n")
        
        # Parse the email
        result = parser.parse(email_path)
        opp = result.opportunity
        
        print("📊 Results:")
        print("-"*100)
        print(f"EBITDA:           ${opp.ebitda_millions}M" if opp.ebitda_millions else "EBITDA:           Not found")
        print(f"Company:          {opp.company_name or 'Not found'}")
        print(f"HQ Location:      {opp.hq_location or 'Not found'}")
        print(f"Raw EBITDA Text:  {opp.raw_ebitda_text or 'N/A'}")
        print(f"Processing Time:  {result.processing_time_seconds:.2f}s")
        print(f"Bounding Boxes:   {len(opp.bounding_boxes)} regions")
        
        if result.errors:
            print(f"\n⚠️  Errors:")
            for error in result.errors:
                print(f"  - {error}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

