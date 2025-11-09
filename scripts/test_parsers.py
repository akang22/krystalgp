"""Quick test script to run parsers on sample emails."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from email_parser.ner_body_parser import NERBodyParser

# Test emails
TEST_EMAILS = [
    "FW Project Toro.msg",
    "FW Project Gravy - Franchise QSR Portfolio Acquisition Opportunity.msg",
    "Project Aberdeen - Krystal Growth Partners .msg",
]

WORKSPACE = Path(__file__).parent.parent
SAMPLE_EMAILS_DIR = WORKSPACE / "sample_emails"


def main():
    """Test parsers on sample emails."""
    print("="*80)
    print("Testing Email Parsers")
    print("="*80)
    
    # Initialize NER parser (no API key needed)
    print("\nInitializing NER Body Parser...")
    ner_parser = NERBodyParser()
    print("✓ NER parser ready")
    
    # Test on each email
    for email_file in TEST_EMAILS:
        email_path = SAMPLE_EMAILS_DIR / email_file
        
        if not email_path.exists():
            print(f"\n✗ Email not found: {email_file}")
            continue
        
        print("\n" + "="*80)
        print(f"📧 Processing: {email_file}")
        print("="*80)
        
        # Parse with NER
        print("\n🔍 NER Body Parser Results:")
        print("-"*80)
        
        try:
            result = ner_parser.parse(email_path)
            opp = result.opportunity
            
            print(f"Source Domain:    {opp.source_domain}")
            print(f"Recipient:        {opp.recipient}")
            print(f"Company Name:     {opp.company_name}")
            print(f"HQ Location:      {opp.hq_location}")
            print(f"EBITDA:           ${opp.ebitda_millions}M" if opp.ebitda_millions else "EBITDA:           Not found")
            print(f"Sector:           {opp.sector}")
            print(f"Date:             {opp.date}")
            print(f"Raw EBITDA Text:  {opp.raw_ebitda_text}")
            print(f"Processing Time:  {result.processing_time_seconds:.2f}s")
            print(f"Extraction Source: {result.extraction_source}")
            
        except Exception as e:
            print(f"✗ Error: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "="*80)
    print("Test Complete!")
    print("="*80)
    print("\nTo test LLM parsers, set OPENAI_API_KEY in .env")
    print("Then run: uv run python scripts/test_parsers_llm.py")


if __name__ == "__main__":
    main()


