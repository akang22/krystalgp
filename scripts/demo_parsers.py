"""Demonstration script to showcase all parser capabilities."""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from email_parser.ner_body_parser import NERBodyParser
from email_parser.llm_body_parser import LLMBodyParser
from email_parser.ocr_attachment_parser import OCRAttachmentParser
from email_parser.layout_attachment_parser import LayoutLLMParser

# Test emails - diverse set
TEST_EMAILS = [
    "FW Project Toro.msg",  # Has EBITDA in email
    "FW Project Gravy - Franchise QSR Portfolio Acquisition Opportunity.msg",  # Has EBITDA
    "FW 2025 Estimated $63.4M $5.2M Cold Plunge Sauna Company.msg",  # EBITDA in filename
]

WORKSPACE = Path(__file__).parent.parent
SAMPLE_EMAILS_DIR = WORKSPACE / "sample_emails"


def print_header(title):
    """Print formatted header."""
    print("\n" + "="*100)
    print(f"  {title}")
    print("="*100)


def print_result(parser_name, result):
    """Print parser result in formatted way."""
    opp = result.opportunity
    
    print(f"\n🔹 {parser_name}")
    print("─"*100)
    
    data = [
        ("Source Domain", opp.source_domain or "Not extracted"),
        ("Recipient", opp.recipient or "Not extracted"),
        ("Company/Project", opp.company_name or "Not extracted"),
        ("HQ Location", opp.hq_location or "Not extracted"),
        ("EBITDA", f"${opp.ebitda_millions}M" if opp.ebitda_millions is not None else "Not extracted"),
        ("Sector", opp.sector or "Not extracted"),
        ("Date", str(opp.date) if opp.date else "Not extracted"),
        ("Raw EBITDA Text", opp.raw_ebitda_text or "N/A"),
        ("Processing Time", f"{result.processing_time_seconds:.2f}s"),
        ("Extraction Source", result.extraction_source),
    ]
    
    for label, value in data:
        print(f"  {label:.<20} {value}")
    
    if opp.bounding_boxes:
        print(f"  {'Bounding Boxes':.<20} {len(opp.bounding_boxes)} regions")


def main():
    """Run demonstration of all parsers."""
    print_header("📧 Email Parser Demonstration")
    
    # Check for API key
    has_api_key = bool(os.getenv('OPENAI_API_KEY'))
    
    # Initialize parsers
    parsers = {}
    
    print("\n🔧 Initializing Parsers...")
    print("-"*100)
    
    # NER parser (always available)
    try:
        parsers['NER Body'] = NERBodyParser()
        print("  ✓ NER Body Parser (spaCy + Regex)")
    except Exception as e:
        print(f"  ✗ NER Body Parser: {e}")
    
    # LLM parsers (require API key)
    if has_api_key:
        try:
            parsers['LLM Body'] = LLMBodyParser()
            print("  ✓ LLM Body Parser (OpenAI GPT-4)")
        except Exception as e:
            print(f"  ✗ LLM Body Parser: {e}")
        
        try:
            parsers['OCR + LLM'] = OCRAttachmentParser()
            print("  ✓ OCR + LLM Attachment Parser (Tesseract + GPT-4)")
        except Exception as e:
            print(f"  ✗ OCR + LLM Parser: {e}")
        
        try:
            parsers['Layout LLM'] = LayoutLLMParser()
            print("  ✓ Layout-Aware LLM Parser (GPT-4-Vision)")
        except Exception as e:
            print(f"  ✗ Layout LLM Parser: {e}")
    else:
        print("  ℹ LLM parsers not available (set OPENAI_API_KEY to enable)")
    
    if not parsers:
        print("\n❌ No parsers available!")
        return
    
    # Process each test email
    for email_file in TEST_EMAILS:
        email_path = SAMPLE_EMAILS_DIR / email_file
        
        if not email_path.exists():
            print(f"\n⚠ Email not found: {email_file}")
            continue
        
        print_header(f"📨 {email_file}")
        
        # Get email metadata
        first_parser = list(parsers.values())[0]
        try:
            email_data = first_parser.extract_msg_file(email_path)
            print(f"\n📋 Email Metadata:")
            print(f"  From: {email_data.sender}")
            print(f"  To: {', '.join(email_data.recipients[:2])}{'...' if len(email_data.recipients) > 2 else ''}")
            print(f"  Subject: {email_data.subject}")
            print(f"  Date: {email_data.date}")
            print(f"  Attachments: {len(email_data.attachments)} files")
            
            if email_data.attachments:
                for att in email_data.attachments[:3]:  # Show first 3
                    print(f"    - {att.filename} ({att.size_bytes / 1024:.1f} KB)")
        except Exception as e:
            print(f"  Error extracting metadata: {e}")
        
        # Run each parser
        for parser_name, parser in parsers.items():
            try:
                result = parser.parse(email_path)
                print_result(parser_name, result)
            except Exception as e:
                print(f"\n🔹 {parser_name}")
                print("─"*100)
                print(f"  ❌ Error: {e}")
    
    # Summary
    print_header("📊 Summary")
    print(f"\n  Emails Processed: {len(TEST_EMAILS)}")
    print(f"  Parsers Used: {len(parsers)}")
    print(f"  Available Parsers: {', '.join(parsers.keys())}")
    
    if not has_api_key:
        print("\n  💡 Tip: Set OPENAI_API_KEY in .env to enable LLM parsers")
    
    print("\n" + "="*100)


if __name__ == "__main__":
    main()


