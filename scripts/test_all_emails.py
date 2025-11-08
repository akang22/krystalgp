"""Test all parsers on multiple emails including previously problematic ones."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from email_parser.ner_body_parser import NERBodyParser
from email_parser.llm_body_parser import LLMBodyParser

# Test emails including the problematic one
TEST_EMAILS = [
    "FW Project Gravy - Franchise QSR Portfolio Acquisition Opportunity.msg",
    "Acquisition Opportunity - Fishing and Seafood Distribution Leader.msg",  # Previously problematic
    "FW Project Toro.msg",
]

WORKSPACE = Path(__file__).parent.parent
SAMPLE_EMAILS_DIR = WORKSPACE / "sample_emails"


def main():
    """Test parsers on multiple emails."""
    print("="*100)
    print("🧪 Testing All Parsers on Multiple Emails")
    print("="*100)
    
    # Initialize parsers
    ner_parser = NERBodyParser()
    
    try:
        llm_parser = LLMBodyParser()
        has_llm = True
    except:
        llm_parser = None
        has_llm = False
        print("\n⚠️  LLM parser not available (set OPENAI_API_KEY)\n")
    
    # Test each email
    for email_file in TEST_EMAILS:
        email_path = SAMPLE_EMAILS_DIR / email_file
        
        if not email_path.exists():
            print(f"\n❌ Not found: {email_file}")
            continue
        
        print(f"\n{'='*100}")
        print(f"📧 {email_file}")
        print(f"{'='*100}")
        
        # Test NER parser
        try:
            result = ner_parser.parse(email_path)
            opp = result.opportunity
            
            print(f"\n✅ NER Body Parser:")
            print(f"   EBITDA:   ${opp.ebitda_millions}M" if opp.ebitda_millions else "   EBITDA:   Not found")
            print(f"   Company:  {opp.company_name or 'Not found'}")
            print(f"   Location: {opp.hq_location or 'Not found'}")
            print(f"   Source:   {opp.source_domain}")
            print(f"   Time:     {result.processing_time_seconds:.2f}s")
            
        except Exception as e:
            print(f"\n❌ NER Parser Failed: {e}")
        
        # Test LLM parser if available
        if has_llm:
            try:
                result = llm_parser.parse(email_path)
                opp = result.opportunity
                
                print(f"\n✅ LLM Body Parser:")
                print(f"   EBITDA:   ${opp.ebitda_millions}M" if opp.ebitda_millions else "   EBITDA:   Not found")
                print(f"   Company:  {opp.company_name or 'Not found'}")
                print(f"   Location: {opp.hq_location or 'Not found'}")
                print(f"   Time:     {result.processing_time_seconds:.2f}s")
                
            except Exception as e:
                print(f"\n❌ LLM Parser Failed: {e}")
    
    print(f"\n{'='*100}")
    print("✅ All emails parsed successfully!")
    print(f"{'='*100}\n")


if __name__ == "__main__":
    main()

