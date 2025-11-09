"""Script to help create ground truth labels for evaluation.

This script runs parsers on sample emails to help create manual annotations.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pandas as pd
from email_parser.llm_body_parser import LLMBodyParser
from email_parser.ner_body_parser import NERBodyParser

# Sample of emails to label (diverse set)
SAMPLE_EMAILS = [
    "Project Aberdeen - Krystal Growth Partners .msg",
    "FW Project Toro.msg",
    "FW Project Gravy - Franchise QSR Portfolio Acquisition Opportunity.msg",
    "Project Provision_ Acquisition Opportunity – Midwest Foodservice Distributor with $30M Revenue.msg",
    "FW 2025 Estimated $63.4M $5.2M Cold Plunge Sauna Company.msg",
    "FW Project Kiln Acquisition Opportunity for Canadian StirredKettle Foods Business.msg",
    "FW Project Elevate - Opportunity to acquire a highly regarded data driven marketing agency.msg",
    "Fwd_ Acquisition Opportunity - Infrared Sauna Business.msg",
    "FW Transaction Opportunity - Leading Canadian Regional Airline.msg",
    "RE Project Monstera - Rapidly Growing Auto Aftermarket Distributor.msg",
    "Acquisition Opportunity - Project Cedar.msg",
    "FW Investment Opportunity adtrackmedia C$10M+ Growth Equity Raise.msg",
    "RE_ For Krystal Growth Partners_ Acquisition Opportunity – Elevator Handrail & Safety Barricade Manufacturer (Western Canada).msg",
    "FW SISP - Teaser - Special D Baking Ltd.  Land Assembly Company (Edmonton) Ltd. .msg",
    "Acquisition Opportunity - Fishing and Seafood Distribution Leader.msg",
]


def main():
    """Generate initial ground truth template."""
    workspace = Path(__file__).parent.parent
    sample_dir = workspace / "sample_emails"
    results_csv = workspace / "results.csv"
    
    # Load results.csv for reference
    results_df = pd.read_csv(results_csv)
    
    # Initialize parsers (only if API key available)
    try:
        llm_parser = LLMBodyParser()
        use_llm = True
    except ValueError:
        print("Warning: OpenAI API key not found. Skipping LLM parser.")
        use_llm = False
    
    ner_parser = NERBodyParser()
    
    # Process each sample email
    ground_truth_data = []
    
    for email_file in SAMPLE_EMAILS:
        email_path = sample_dir / email_file
        
        if not email_path.exists():
            print(f"Skipping {email_file} - not found")
            continue
        
        print(f"\nProcessing: {email_file}")
        print("=" * 80)
        
        # Parse with NER
        ner_result = ner_parser.parse(email_path)
        ner_opp = ner_result.opportunity
        
        print(f"NER Parser Results:")
        print(f"  Source: {ner_opp.source_domain}")
        print(f"  Recipient: {ner_opp.recipient}")
        print(f"  HQ Location: {ner_opp.hq_location}")
        print(f"  EBITDA: ${ner_opp.ebitda_millions}M")
        print(f"  Company: {ner_opp.company_name}")
        print(f"  Sector: {ner_opp.sector}")
        print(f"  Raw EBITDA: {ner_opp.raw_ebitda_text}")
        
        # Parse with LLM if available
        llm_opp = None
        if use_llm:
            llm_result = llm_parser.parse(email_path)
            llm_opp = llm_result.opportunity
            
            print(f"\nLLM Parser Results:")
            print(f"  Source: {llm_opp.source_domain}")
            print(f"  Recipient: {llm_opp.recipient}")
            print(f"  HQ Location: {llm_opp.hq_location}")
            print(f"  EBITDA: ${llm_opp.ebitda_millions}M")
            print(f"  Company: {llm_opp.company_name}")
            print(f"  Sector: {llm_opp.sector}")
        
        # Check results.csv for EBITDA reference
        company_match = results_df[
            results_df['Company / Project Name'].str.contains(
                ner_opp.company_name or email_file, case=False, na=False
            )
        ]
        
        reference_ebitda = None
        if not company_match.empty:
            reference_ebitda = company_match.iloc[0]['LTM EBITDA ($M)']
            print(f"\nReference EBITDA from results.csv: {reference_ebitda}")
        
        # Create ground truth row
        row = {
            'email_file': email_file,
            'source_domain': llm_opp.source_domain if llm_opp else ner_opp.source_domain,
            'recipient': llm_opp.recipient if llm_opp else ner_opp.recipient,
            'hq_location': '',  # TO BE MANUALLY FILLED
            'ebitda_millions': reference_ebitda if reference_ebitda and str(reference_ebitda) != 'n.a.' else '',
            'company_name': llm_opp.company_name if llm_opp else ner_opp.company_name or '',
            'sector': llm_opp.sector if llm_opp else ner_opp.sector or '',
            'data_source': '',  # body, attachment, or both
            'notes': f'NER_EBITDA:{ner_opp.ebitda_millions}, LLM_EBITDA:{llm_opp.ebitda_millions if llm_opp else "N/A"}',
        }
        
        ground_truth_data.append(row)
    
    # Create DataFrame
    gt_df = pd.DataFrame(ground_truth_data)
    
    # Save to CSV
    output_path = workspace / "data" / "ground_truth_labels.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gt_df.to_csv(output_path, index=False)
    
    print(f"\n{'='*80}")
    print(f"Ground truth template saved to: {output_path}")
    print(f"Total emails: {len(ground_truth_data)}")
    print("\nNext steps:")
    print("1. Review and manually verify/correct each field in the CSV")
    print("2. Fill in hq_location and data_source columns")
    print("3. Verify EBITDA values against source documents")
    print("4. Add any missing companies not in results.csv")


if __name__ == "__main__":
    main()


