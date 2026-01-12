"""Test parsers on the Pet Food Business email to verify signature stripping."""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from email_parser.llm_body_parser import LLMBodyParser
from email_parser.ensemble_parser import EnsembleParser

WORKSPACE = Path(__file__).parent.parent
SAMPLE_EMAILS_DIR = WORKSPACE / "sample_emails"
EMAIL_FILE = "Acquisition Opportunity – Leading North American Pet Food Business.msg"


def print_result(parser_name, result):
    """Print parser result in formatted way."""
    opp = result.opportunity
    
    print(f"\n{'='*80}")
    print(f"🔹 {parser_name}")
    print(f"{'='*80}")
    
    data = [
        ("Company/Project", opp.company_name or "N/A"),
        ("HQ Location", opp.hq_location or "N/A"),
        ("EBITDA", f"${opp.ebitda_millions}M" if opp.ebitda_millions is not None else "N/A"),
        ("Sector", opp.sector or "N/A"),
        ("Description", opp.description or "N/A"),
        ("Processing Time", f"{result.processing_time_seconds:.2f}s"),
    ]
    
    for label, value in data:
        print(f"  {label:.<25} {value}")
    
    # Show location options if available
    if opp.location_options:
        print(f"\n  Location Options:")
        for loc_opt in opp.location_options[:5]:  # Show first 5
            print(f"    - {loc_opt.value} (confidence: {loc_opt.confidence:.2f}, source: {loc_opt.source})")


def main():
    """Test parsers on Pet Food Business email."""
    print("="*80)
    print("Testing Parsers on: Leading North American Pet Food Business")
    print("="*80)
    
    email_path = SAMPLE_EMAILS_DIR / EMAIL_FILE
    
    if not email_path.exists():
        print(f"❌ Email not found: {email_path}")
        return
    
    # Check for API key
    if not os.getenv('OPENAI_API_KEY'):
        print("❌ OPENAI_API_KEY not set. Please set it in .env file.")
        return
    
    # Initialize parsers
    print("\n🔧 Initializing Parsers...")
    try:
        llm_parser = LLMBodyParser()
        print("  ✓ LLM Body Parser initialized")
    except Exception as e:
        print(f"  ✗ LLM Body Parser failed: {e}")
        return
    
    try:
        ensemble_parser = EnsembleParser(use_llm=True, use_vision=True, use_ocr=False)
        print("  ✓ Ensemble Parser initialized")
    except Exception as e:
        print(f"  ✗ Ensemble Parser failed: {e}")
        return
    
    # Extract email data
    print(f"\n📧 Extracting email data from: {EMAIL_FILE}")
    try:
        email_data = llm_parser.extract_msg_file(email_path)
        print(f"  From: {email_data.sender}")
        print(f"  Subject: {email_data.subject}")
        print(f"  Date: {email_data.date}")
        print(f"  Body length: {len(email_data.body_plain or '')} chars")
        
        # Show a preview of the body (last 500 chars to see signature)
        if email_data.body_plain:
            print(f"\n  Original body preview (last 500 chars):")
            print("  " + "-"*76)
            preview = email_data.body_plain[-500:]
            for line in preview.split('\n'):
                print(f"  {line}")
            print("  " + "-"*76)
            
            # Test signature stripping
            print(f"\n  Testing signature stripping...")
            cleaned_body = llm_parser._strip_email_signature_with_llm(email_data.body_plain)
            if len(cleaned_body) < len(email_data.body_plain):
                print(f"  ✓ Signature stripped: {len(email_data.body_plain)} -> {len(cleaned_body)} chars")
                print(f"\n  Cleaned body preview (last 300 chars):")
                print("  " + "-"*76)
                cleaned_preview = cleaned_body[-300:] if len(cleaned_body) > 300 else cleaned_body
                for line in cleaned_preview.split('\n'):
                    print(f"  {line}")
                print("  " + "-"*76)
            else:
                print(f"  ⚠ No signature detected (length unchanged)")
    except Exception as e:
        print(f"  ❌ Error extracting email: {e}")
        return
    
    # Test LLM Body Parser
    print(f"\n{'='*80}")
    print("Testing LLM Body Parser")
    print(f"{'='*80}")
    try:
        result = llm_parser.parse(email_path)
        print_result("LLM Body Parser", result)
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    # Test Ensemble Parser
    print(f"\n{'='*80}")
    print("Testing Ensemble Parser")
    print(f"{'='*80}")
    try:
        result = ensemble_parser.parse(email_path)
        print_result("Ensemble Parser", result)
    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n{'='*80}")
    print("Test Complete")
    print(f"{'='*80}")
    print("\n💡 Expected: Location should NOT be 'Vancouver, BC' if it only appears in signature")
    print("   If location is extracted, check if it appears in the main body content.")


if __name__ == "__main__":
    main()
