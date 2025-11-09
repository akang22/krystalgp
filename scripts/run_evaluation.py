"""Run full evaluation of all parsers on sample emails.

This script runs all available parsers on the sample emails,
generates comparison metrics, and saves results.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pandas as pd
from datetime import datetime
from tqdm import tqdm

from email_parser.llm_body_parser import LLMBodyParser
from email_parser.ner_body_parser import NERBodyParser
from email_parser.ocr_attachment_parser import OCRAttachmentParser
from email_parser.layout_attachment_parser import LayoutLLMParser
from email_parser.utils import fuzzy_match_ebitda


# Paths
WORKSPACE = Path(__file__).parent.parent
SAMPLE_EMAILS_DIR = WORKSPACE / "sample_emails"
GROUND_TRUTH_PATH = WORKSPACE / "data" / "ground_truth_labels.csv"
OUTPUT_PATH = WORKSPACE / "data" / "comparison_results.csv"


def main():
    """Run evaluation."""
    print("="*80)
    print("Email Parser Evaluation")
    print("="*80)
    
    # Load ground truth
    if not GROUND_TRUTH_PATH.exists():
        print(f"Error: Ground truth file not found: {GROUND_TRUTH_PATH}")
        return
    
    ground_truth = pd.read_csv(GROUND_TRUTH_PATH)
    print(f"\nLoaded {len(ground_truth)} ground truth labels")
    
    # Initialize parsers
    parsers = {}
    
    print("\nInitializing parsers...")
    
    try:
        parsers['LLM_Body'] = LLMBodyParser()
        print("  ✓ LLM Body Parser")
    except ValueError:
        print("  ✗ LLM Body Parser (API key not found)")
    
    try:
        parsers['NER_Body'] = NERBodyParser()
        print("  ✓ NER Body Parser")
    except Exception as e:
        print(f"  ✗ NER Body Parser ({e})")
    
    try:
        parsers['OCR_Attachment'] = OCRAttachmentParser()
        print("  ✓ OCR Attachment Parser")
    except ValueError:
        print("  ✗ OCR Attachment Parser (API key not found)")
    
    try:
        parsers['Layout_Attachment'] = LayoutLLMParser()
        print("  ✓ Layout LLM Parser")
    except ValueError:
        print("  ✗ Layout LLM Parser (API key not found)")
    
    if not parsers:
        print("\nNo parsers available. Please check your configuration.")
        return
    
    # Process emails
    print(f"\nProcessing {len(ground_truth)} emails...")
    
    results_data = []
    
    for _, row in tqdm(ground_truth.iterrows(), total=len(ground_truth)):
        email_file = row['email_file']
        email_path = SAMPLE_EMAILS_DIR / email_file
        
        if not email_path.exists():
            print(f"  Warning: {email_file} not found")
            continue
        
        result_row = {
            'email_file': email_file,
            'gt_ebitda': row.get('ebitda_millions'),
            'gt_company': row.get('company_name'),
            'gt_location': row.get('hq_location'),
            'gt_sector': row.get('sector'),
        }
        
        # Run each parser
        for parser_name, parser in parsers.items():
            try:
                parse_result = parser.parse(email_path)
                opp = parse_result.opportunity
                
                result_row[f'{parser_name}_ebitda'] = opp.ebitda_millions
                result_row[f'{parser_name}_company'] = opp.company_name
                result_row[f'{parser_name}_location'] = opp.hq_location
                result_row[f'{parser_name}_sector'] = opp.sector
                result_row[f'{parser_name}_source'] = opp.source_domain
                result_row[f'{parser_name}_time'] = parse_result.processing_time_seconds
                
                # Calculate accuracy
                if not pd.isna(row.get('ebitda_millions')) and row['ebitda_millions'] != '':
                    expected = float(row['ebitda_millions'])
                    result_row[f'{parser_name}_ebitda_match'] = fuzzy_match_ebitda(
                        opp.ebitda_millions, expected, tolerance=0.5
                    )
                
            except Exception as e:
                print(f"  Error with {parser_name} on {email_file}: {e}")
                result_row[f'{parser_name}_error'] = str(e)
        
        results_data.append(result_row)
    
    # Create results DataFrame
    results_df = pd.DataFrame(results_data)
    
    # Save results
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    results_df.to_csv(OUTPUT_PATH, index=False)
    print(f"\n✓ Results saved to: {OUTPUT_PATH}")
    
    # Calculate summary statistics
    print("\n" + "="*80)
    print("Summary Statistics")
    print("="*80)
    
    for parser_name in parsers.keys():
        ebitda_col = f'{parser_name}_ebitda_match'
        
        if ebitda_col in results_df.columns:
            accuracy = results_df[ebitda_col].sum() / results_df[ebitda_col].count()
            avg_time = results_df[f'{parser_name}_time'].mean()
            
            print(f"\n{parser_name}:")
            print(f"  EBITDA Accuracy: {accuracy:.1%}")
            print(f"  Avg Processing Time: {avg_time:.2f}s")
    
    print("\n" + "="*80)
    print("Evaluation Complete!")
    print("="*80)
    print(f"\nNext steps:")
    print(f"1. Review results: {OUTPUT_PATH}")
    print(f"2. Launch Streamlit dashboard: streamlit run streamlit_app.py")
    print(f"3. Analyze accuracy and performance metrics")


if __name__ == "__main__":
    main()


