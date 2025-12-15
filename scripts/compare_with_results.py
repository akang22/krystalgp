"""Compare parser results against results.csv.

This script runs the parser on all emails found in results.csv and generates
a comparison report for critical columns.
"""

import os
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

load_dotenv()

from email_parser.base import EmailData
from email_parser.ensemble_parser import EnsembleParser
from email_parser.llm_body_parser import LLMBodyParser

# Paths
WORKSPACE = Path(__file__).parent.parent
SAMPLE_EMAILS_DIR = WORKSPACE / "sample_emails"
RESULTS_CSV = WORKSPACE / "results.csv"


def find_email_file(project_name: str, date_received: str) -> Optional[Path]:
    """Find email file matching project name or date.
    
    Args:
        project_name: Project name from results.csv
        date_received: Date received string
        
    Returns:
        Path to email file if found, None otherwise
    """
    if not SAMPLE_EMAILS_DIR.exists():
        return None
    
    # Try exact project name match
    project_name_clean = project_name.strip()
    for email_file in SAMPLE_EMAILS_DIR.glob("*.msg"):
        filename_lower = email_file.name.lower()
        project_lower = project_name_clean.lower()
        
        # Check if project name appears in filename
        if project_lower in filename_lower or filename_lower in project_lower:
            return email_file
        
        # Also try partial matches (e.g., "Project Gravy" matches "FW Project Gravy...")
        if project_lower.replace("project ", "") in filename_lower:
            return email_file
    
    return None


def parse_ebitda_value(ebitda_str: str) -> Optional[float]:
    """Parse EBITDA string to float.
    
    Args:
        ebitda_str: EBITDA string like "$5.2M", "5.2", "n.a.", etc.
        
    Returns:
        Float value or None
    """
    if pd.isna(ebitda_str) or not ebitda_str:
        return None
    
    ebitda_str = str(ebitda_str).strip()
    
    # Handle "n.a.", "N/A", etc.
    if ebitda_str.lower() in ["n.a.", "n/a", "na", "-", ""]:
        return None
    
    # Remove $ and M, then convert
    try:
        cleaned = ebitda_str.replace("$", "").replace("M", "").replace(",", "").strip()
        return float(cleaned)
    except (ValueError, AttributeError):
        return None


def extract_domain_from_source(source_str: str) -> Optional[str]:
    """Extract domain from source string.
    
    Args:
        source_str: Source string like "CIBC Mid-Market (Toronto)" or "cibc.com"
        
    Returns:
        Domain string or None
    """
    if pd.isna(source_str) or not source_str:
        return None
    
    source_str = str(source_str).strip()
    
    # If it already looks like a domain, return it
    if "." in source_str and " " not in source_str:
        return source_str.lower()
    
    # Try to extract domain from email data
    return None


def calculate_investment_criteria_fit(
    hq_location: Optional[str], ebitda: Optional[float]
) -> str:
    """Calculate investment criteria fit.
    
    Args:
        hq_location: Headquarters location
        ebitda: EBITDA in millions
        
    Returns:
        "Yes" or "No"
    """
    if not hq_location or not ebitda:
        return "No"
    
    hq_lower = hq_location.lower()
    
    # Check if HQ is in Western Canada (BC or Alberta)
    is_western_canada = (
        "bc" in hq_lower
        or "british columbia" in hq_lower
        or "alberta" in hq_lower
        or "ab" in hq_lower
        or "vancouver" in hq_lower
        or "calgary" in hq_lower
        or "edmonton" in hq_lower
    )
    
    # Check if EBITDA is between 2-8M
    ebitda_in_range = 2.0 <= ebitda <= 8.0
    
    return "Yes" if (is_western_canada and ebitda_in_range) else "No"


def main():
    """Run comparison against results.csv."""
    print("=" * 100)
    print("Parser Comparison Against results.csv")
    print("=" * 100)
    
    # Load results.csv
    if not RESULTS_CSV.exists():
        print(f"Error: {RESULTS_CSV} not found")
        return
    
    results_df = pd.read_csv(RESULTS_CSV)
    print(f"\nLoaded {len(results_df)} rows from results.csv")
    
    # Initialize parser
    try:
        parser = EnsembleParser()
        print("✓ Parser initialized")
    except Exception as e:
        print(f"Error initializing parser: {e}")
        return
    
    # Process each row
    comparison_data = []
    emails_found = 0
    emails_processed = 0
    
    for idx, row in results_df.iterrows():
        project_name = row.get("Company / Project Name", "")
        date_received = row.get("Date Received", "")
        
        if pd.isna(project_name) or not project_name:
            continue
        
        # Find email file
        email_file = find_email_file(project_name, date_received)
        
        if not email_file:
            continue
        
        emails_found += 1
        
        # Parse email
        try:
            # Use a concrete parser to extract email data
            temp_parser = LLMBodyParser() if os.getenv("OPENAI_API_KEY") else None
            if temp_parser:
                email_data = temp_parser.extract_msg_file(email_file)
            else:
                # Fallback: create a simple parser just for extraction
                from email_parser.ner_body_parser import NERBodyParser
                temp_parser = NERBodyParser()
                email_data = temp_parser.extract_msg_file(email_file)
            
            opp = parser.parse_data(email_data)
            
            if not opp:
                continue
            emails_processed += 1
            
            # Extract values from results.csv
            csv_ebitda = parse_ebitda_value(row.get("LTM EBITDA ($M)", ""))
            csv_source = row.get("Source", "")
            csv_project = row.get("Company / Project Name", "")
            csv_date = row.get("Date Received", "")
            csv_criteria = row.get("Investment Criteria Fit?", "")
            
            # Extract values from parser
            parsed_ebitda = opp.ebitda_millions
            parsed_source = opp.source_domain or ""
            parsed_project = opp.company_name or ""
            parsed_date = (
                opp.date.strftime("%d-%b-%y") if opp.date else None
            )  # Format like "15-Oct-25"
            parsed_hq = opp.hq_location or ""
            parsed_ebitda_for_calc = parsed_ebitda
            parsed_criteria = calculate_investment_criteria_fit(
                parsed_hq, parsed_ebitda_for_calc
            )
            
            # Compare
            ebitda_match = (
                abs(csv_ebitda - parsed_ebitda) < 0.1
                if csv_ebitda is not None and parsed_ebitda is not None
                else (csv_ebitda is None and parsed_ebitda is None)
            )
            
            # Source comparison - try to match domain
            source_match = False
            if csv_source and parsed_source:
                csv_lower = str(csv_source).lower()
                parsed_lower = str(parsed_source).lower()
                # Check if domain appears in source or vice versa
                source_match = (
                    parsed_lower in csv_lower
                    or csv_lower in parsed_lower
                    or any(
                        word in parsed_lower
                        for word in csv_lower.split()
                        if len(word) > 3
                    )
                )
            
            project_match = (
                str(csv_project).lower() in str(parsed_project).lower()
                or str(parsed_project).lower() in str(csv_project).lower()
                if csv_project and parsed_project
                else False
            )
            
            date_match = (
                str(csv_date).lower() == str(parsed_date).lower()
                if csv_date and parsed_date
                else False
            )
            
            # Only compare criteria if it's Yes/No in CSV
            criteria_match = None
            if csv_criteria and str(csv_criteria).strip().lower() in ["yes", "no"]:
                criteria_match = (
                    str(csv_criteria).strip().lower()
                    == str(parsed_criteria).strip().lower()
                )
            
            comparison_data.append(
                {
                    "Email File": email_file.name,
                    "Project Name (CSV)": csv_project,
                    "Project Name (Parsed)": parsed_project,
                    "Project Match": "✓" if project_match else "✗",
                    "LTM EBITDA (CSV)": csv_ebitda,
                    "LTM EBITDA (Parsed)": parsed_ebitda,
                    "EBITDA Match": "✓" if ebitda_match else "✗",
                    "Source (CSV)": csv_source,
                    "Source (Parsed)": parsed_source,
                    "Source Match": "✓" if source_match else "✗",
                    "Date Received (CSV)": csv_date,
                    "Date Received (Parsed)": parsed_date,
                    "Date Match": "✓" if date_match else "✗",
                    "Investment Criteria (CSV)": csv_criteria,
                    "Investment Criteria (Parsed)": parsed_criteria,
                    "Criteria Match": "✓" if criteria_match else ("✗" if criteria_match is False else "N/A"),
                }
            )
            
            if emails_processed % 10 == 0:
                print(f"Processed {emails_processed} emails...")
        
        except Exception as e:
            print(f"Error processing {email_file.name}: {e}")
            continue
    
    print(f"\nFound {emails_found} email files")
    print(f"Successfully processed {emails_processed} emails")
    
    if not comparison_data:
        print("No comparison data generated")
        return
    
    # Create comparison DataFrame
    comparison_df = pd.DataFrame(comparison_data)
    
    # Save to CSV
    output_file = WORKSPACE / "parser_comparison_results.csv"
    comparison_df.to_csv(output_file, index=False)
    print(f"\n✓ Saved comparison results to {output_file}")
    
    # Print summary statistics
    print("\n" + "=" * 100)
    print("SUMMARY STATISTICS")
    print("=" * 100)
    
    total = len(comparison_df)
    
    print(f"\nTotal comparisons: {total}")
    print(f"\nMatch rates:")
    print(f"  Project Name: {comparison_df['Project Match'].value_counts().get('✓', 0)}/{total} ({100*comparison_df['Project Match'].value_counts().get('✓', 0)/total:.1f}%)")
    print(f"  LTM EBITDA: {comparison_df['EBITDA Match'].value_counts().get('✓', 0)}/{total} ({100*comparison_df['EBITDA Match'].value_counts().get('✓', 0)/total:.1f}%)")
    print(f"  Source: {comparison_df['Source Match'].value_counts().get('✓', 0)}/{total} ({100*comparison_df['Source Match'].value_counts().get('✓', 0)/total:.1f}%)")
    print(f"  Date Received: {comparison_df['Date Match'].value_counts().get('✓', 0)}/{total} ({100*comparison_df['Date Match'].value_counts().get('✓', 0)/total:.1f}%)")
    
    criteria_comparisons = comparison_df[comparison_df['Criteria Match'] != 'N/A']
    if len(criteria_comparisons) > 0:
        criteria_total = len(criteria_comparisons)
        criteria_matches = criteria_comparisons['Criteria Match'].value_counts().get('✓', 0)
        print(f"  Investment Criteria: {criteria_matches}/{criteria_total} ({100*criteria_matches/criteria_total:.1f}%)")
    
    # Print detailed comparison table
    print("\n" + "=" * 100)
    print("DETAILED COMPARISON (first 20 rows)")
    print("=" * 100)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', None)
    pd.set_option('display.max_colwidth', 30)
    print(comparison_df.head(20).to_string(index=False))
    
    if len(comparison_df) > 20:
        print(f"\n... and {len(comparison_df) - 20} more rows (see {output_file} for full results)")


if __name__ == "__main__":
    main()

