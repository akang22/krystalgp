"""Test all parsers on sample emails with comparison."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from email_parser.ner_body_parser import NERBodyParser
from email_parser.llm_body_parser import LLMBodyParser
from email_parser.ocr_attachment_parser import OCRAttachmentParser
from email_parser.ocr_ner_parser import OCRNERParser
from email_parser.layout_attachment_parser import LayoutLLMParser
from email_parser.ensemble_parser import EnsembleParser

# Test on one email with all parsers
TEST_EMAIL = "FW Project Gravy - Franchise QSR Portfolio Acquisition Opportunity.msg"

WORKSPACE = Path(__file__).parent.parent
SAMPLE_EMAILS_DIR = WORKSPACE / "sample_emails"


def main():
    """Test all parsers on one email."""
    print("="*100)
    print("🧪 Testing All Parsers - Side by Side Comparison")
    print("="*100)
    
    email_path = SAMPLE_EMAILS_DIR / TEST_EMAIL
    
    if not email_path.exists():
        print(f"❌ Email not found: {TEST_EMAIL}")
        return
    
    print(f"\n📧 Testing: {TEST_EMAIL}")
    print("-"*100)
    
    # Initialize all parsers
    parsers = {
        'NER Body': NERBodyParser(),
        'LLM Body': LLMBodyParser(),
        'OCR + LLM': OCRAttachmentParser(),
        'OCR + NER': OCRNERParser(),
        'Layout Vision': LayoutLLMParser(),
        'Final Results': EnsembleParser(
            use_llm=True,
            use_ner=True,
            use_vision=True,
            use_ocr=False,
            results_csv_path=WORKSPACE / "results.csv"
        ),
    }
    
    print(f"\n✓ All 6 parsers initialized (including Ensemble)\n")
    
    # Run each parser
    results = {}
    for name, parser in parsers.items():
        print(f"🔄 Running {name}...")
        try:
            result = parser.parse(email_path)
            results[name] = result
            print(f"   ✓ Complete in {result.processing_time_seconds:.2f}s")
        except Exception as e:
            print(f"   ❌ Error: {e}")
            results[name] = None
    
    # Display comparison table
    print("\n" + "="*100)
    print("📊 RESULTS COMPARISON")
    print("="*100)
    
    print(f"\n{'Parser':<20} {'EBITDA':<15} {'Company':<25} {'HQ Location':<20} {'Time (s)':<10}")
    print("-"*100)
    
    for name, result in results.items():
        if result:
            opp = result.opportunity
            ebitda = f"${opp.ebitda_millions:.2f}M" if opp.ebitda_millions else "Not found"
            company = (opp.company_name or "Not found")[:24]
            location = (opp.hq_location or "Not found")[:19]
            time = f"{result.processing_time_seconds:.2f}"
            
            print(f"{name:<20} {ebitda:<15} {company:<25} {location:<20} {time:<10}")
        else:
            print(f"{name:<20} {'Error':<15} {'Error':<25} {'Error':<20} {'N/A':<10}")
    
    # Detailed results
    print("\n" + "="*100)
    print("📋 DETAILED RESULTS")
    print("="*100)
    
    for name, result in results.items():
        if result:
            opp = result.opportunity
            print(f"\n🔹 {name}")
            print("-"*100)
            print(f"  EBITDA:           ${opp.ebitda_millions:.2f}M" if opp.ebitda_millions else "  EBITDA:           Not found")
            print(f"  Company:          {opp.company_name or 'Not found'}")
            print(f"  HQ Location:      {opp.hq_location or 'Not found'}")
            print(f"  Sector:           {opp.sector or 'Not found'}")
            print(f"  Source Domain:    {opp.source_domain or 'Not found'}")
            print(f"  Recipient:        {opp.recipient or 'Not found'}")
            print(f"  Raw EBITDA Text:  {opp.raw_ebitda_text or 'N/A'}")
            print(f"  Processing Time:  {result.processing_time_seconds:.2f}s")
            print(f"  Data Source:      {result.extraction_source}")
    
    print("\n" + "="*100)
    print("✅ Test Complete!")
    print("="*100)


if __name__ == "__main__":
    main()

