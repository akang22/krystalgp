"""Compare parser results against results.csv.

This script:
1. Parses ALL emails in sample_emails directory
2. Extracts company/project names from each email
3. Matches parsed results to results.csv by project name
4. Includes all parsed emails (even if not found in results.csv)
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
MAPPING_CSV = WORKSPACE / "email_to_project_mapping.csv"


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


def normalize_project_name(name: str) -> str:
    """Normalize project name for matching.

    Args:
        name: Project name string

    Returns:
        Normalized name (lowercase, stripped, common variations removed)
    """
    if not name or pd.isna(name):
        return ""
    
    name = str(name).strip().lower()
    # Remove common prefixes
    name = name.replace("project ", "").strip()
    return name


def match_project_name(parsed_name: str, csv_name: str) -> bool:
    """Check if parsed project name matches CSV project name.

    Args:
        parsed_name: Project name from parser
        csv_name: Project name from CSV

    Returns:
        True if they match (fuzzy matching)
    """
    parsed_norm = normalize_project_name(parsed_name)
    csv_norm = normalize_project_name(csv_name)
    
    if not parsed_norm or not csv_norm:
        return False
    
    # Exact match
    if parsed_norm == csv_norm:
        return True
    
    # One contains the other
    if parsed_norm in csv_norm or csv_norm in parsed_norm:
        return True
    
    # Check if key words match (for cases like "Project Gravy" vs "Gravy")
    parsed_words = set(w for w in parsed_norm.split() if len(w) > 3)
    csv_words = set(w for w in csv_norm.split() if len(w) > 3)
    
    if parsed_words and csv_words:
        # If significant overlap in key words
        overlap = len(parsed_words & csv_words)
        if overlap >= min(len(parsed_words), len(csv_words)) * 0.5:
            return True
    
    return False


def find_matching_csv_row(
    mapped_project_name: Optional[str], 
    parsed_project_name: str, 
    results_df: pd.DataFrame
) -> Optional[pd.Series]:
    """Find matching row in results.csv by project name.

    Args:
        mapped_project_name: Project name from email_to_project_mapping.csv (if available)
        parsed_project_name: Project name from parser (fallback)
        results_df: DataFrame from results.csv

    Returns:
        Matching row if found, None otherwise
    """
    # First try to use the mapped project name if available
    project_name_to_match = mapped_project_name if mapped_project_name else parsed_project_name
    
    if not project_name_to_match:
        return None
    
    # Try exact match first (case-insensitive)
    for idx, row in results_df.iterrows():
        csv_project_name = row.get("Company / Project Name", "")
        if pd.isna(csv_project_name) or not csv_project_name:
            continue
        
        # Exact match (case-insensitive)
        if str(csv_project_name).strip().lower() == str(project_name_to_match).strip().lower():
            return row
    
    # If no exact match, try fuzzy matching
    for idx, row in results_df.iterrows():
        csv_project_name = row.get("Company / Project Name", "")
        if pd.isna(csv_project_name) or not csv_project_name:
            continue
        
        if match_project_name(project_name_to_match, csv_project_name):
            return row
    
    return None


def calculate_investment_criteria_fit(hq_location: Optional[str], ebitda: Optional[float]) -> str:
    """Calculate investment criteria fit.

    Args:
        hq_location: Headquarters location
        ebitda: EBITDA in millions

    Returns:
        "Yes" or "No"
    """
    if not hq_location or not ebitda:
        return "No"

    # Hardcoded list of 25 populous cities in BC and Alberta
    # BC cities (15): Vancouver, Victoria, Surrey, Burnaby, Richmond, Coquitlam, 
    # Langley, Abbotsford, North Vancouver, West Vancouver, Kelowna, Kamloops, 
    # Nanaimo, Prince George, Chilliwack
    # Alberta cities (10): Calgary, Edmonton, Red Deer, Lethbridge, St. Albert, 
    # Medicine Hat, Grande Prairie, Airdrie, Spruce Grove, Fort McMurray
    western_canada_cities = [
        # BC cities
        "vancouver", "victoria", "surrey", "burnaby", "richmond",
        "coquitlam", "langley", "abbotsford", "north vancouver", "west vancouver",
        "kelowna", "kamloops", "nanaimo", "prince george", "chilliwack",
        # Alberta cities
        "calgary", "edmonton", "red deer", "lethbridge", "st. albert",
        "medicine hat", "grande prairie", "airdrie", "spruce grove", "fort mcmurray",
    ]

    hq_lower = hq_location.lower()

    # Check if HQ is in Western Canada (BC or Alberta)
    # First check for province abbreviations/names
    is_western_canada = (
        "bc" in hq_lower
        or "british columbia" in hq_lower
        or "alberta" in hq_lower
        or "ab" in hq_lower
    )
    
    # Check for regional terms indicating Western Canada
    if not is_western_canada:
        western_terms = [
            "west coast",
            "western canada",
            "western canadian",
            "bc-based",
            "alberta-based",
            "pacific coast",  # BC is on the Pacific
        ]
        for term in western_terms:
            if term in hq_lower:
                is_western_canada = True
                break
    
    # Check for major cities if province not found
    if not is_western_canada:
        for city in western_canada_cities:
            if city in hq_lower:
                is_western_canada = True
                break

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

    # Load email-to-project mapping
    mapping_df = None
    if MAPPING_CSV.exists():
        mapping_df = pd.read_csv(MAPPING_CSV)
        # Create a dictionary for quick lookup: email_filename -> project_name
        email_to_project = dict(zip(
            mapping_df["Email File"].str.strip(),
            mapping_df["Project Name"].str.strip()
        ))
        print(f"Loaded {len(email_to_project)} email-to-project mappings")
    else:
        print(f"Warning: {MAPPING_CSV} not found, will use parsed project names for matching")
        email_to_project = {}

    # Initialize parser
    try:
        parser = EnsembleParser()
        print("✓ Parser initialized")
    except Exception as e:
        print(f"Error initializing parser: {e}")
        return

    # Get all email files
    if not SAMPLE_EMAILS_DIR.exists():
        print(f"Error: {SAMPLE_EMAILS_DIR} not found")
        return

    email_files = list(SAMPLE_EMAILS_DIR.glob("*.msg"))
    print(f"\nFound {len(email_files)} email files to process")

    # Process each email
    comparison_data = []
    emails_processed = 0
    emails_matched = 0

    for email_file in email_files:
        print(f"\nProcessing: {email_file.name}")

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
                print(f"  ⚠️  No opportunity extracted")
                continue

            emails_processed += 1

            # Extract parsed values
            parsed_ebitda = opp.ebitda_millions
            parsed_source = opp.source_domain or ""
            parsed_project = opp.company_name or ""
            parsed_date = (
                opp.date.strftime("%d-%b-%y") if opp.date else None
            )  # Format like "15-Oct-25"
            parsed_hq = opp.hq_location or ""
            parsed_ebitda_for_calc = parsed_ebitda
            parsed_criteria = calculate_investment_criteria_fit(parsed_hq, parsed_ebitda_for_calc)

            # Get mapped project name from email_to_project_mapping.csv if available
            mapped_project_name = email_to_project.get(email_file.name.strip(), None)
            if mapped_project_name:
                print(f"  📋 Using mapped project name: {mapped_project_name}")

            # Try to find matching row in results.csv using mapped name (or parsed as fallback)
            csv_row = find_matching_csv_row(mapped_project_name, parsed_project, results_df)

            if csv_row is not None:
                emails_matched += 1
                # Extract values from results.csv
                csv_ebitda = parse_ebitda_value(csv_row.get("LTM EBITDA ($M)", ""))
                csv_source = csv_row.get("Source", "")
                csv_project = csv_row.get("Company / Project Name", "")
                csv_date = csv_row.get("Date Received", "")
                csv_criteria = csv_row.get("Investment Criteria Fit?", "")

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
                        or any(word in parsed_lower for word in csv_lower.split() if len(word) > 3)
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
                        str(csv_criteria).strip().lower() == str(parsed_criteria).strip().lower()
                    )

                comparison_data.append(
                    {
                        "Email File": email_file.name,
                        "Project Name (Mapped)": mapped_project_name or "N/A",
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
                        "Criteria Match": (
                            "✓" if criteria_match else ("✗" if criteria_match is False else "N/A")
                        ),
                        "Matched in CSV": "Yes",
                    }
                )
                print(f"  ✓ Matched to CSV: {csv_project}")
            else:
                # No match found in CSV - include anyway for manual review
                comparison_data.append(
                    {
                        "Email File": email_file.name,
                        "Project Name (Mapped)": mapped_project_name or "N/A",
                        "Project Name (CSV)": "NOT FOUND",
                        "Project Name (Parsed)": parsed_project,
                        "Project Match": "N/A",
                        "LTM EBITDA (CSV)": None,
                        "LTM EBITDA (Parsed)": parsed_ebitda,
                        "EBITDA Match": "N/A",
                        "Source (CSV)": "NOT FOUND",
                        "Source (Parsed)": parsed_source,
                        "Source Match": "N/A",
                        "Date Received (CSV)": "NOT FOUND",
                        "Date Received (Parsed)": parsed_date,
                        "Date Match": "N/A",
                        "Investment Criteria (CSV)": "NOT FOUND",
                        "Investment Criteria (Parsed)": parsed_criteria,
                        "Criteria Match": "N/A",
                        "Matched in CSV": "No",
                    }
                )
                print(f"  ⚠️  No match in CSV (parsed: {parsed_project})")

            if emails_processed % 10 == 0:
                print(f"\nProgress: {emails_processed} emails processed, {emails_matched} matched...")

        except Exception as e:
            print(f"  ❌ Error processing {email_file.name}: {e}")
            import traceback
            traceback.print_exc()
            continue

    print(f"\n{'='*100}")
    print(f"Processing complete!")
    print(f"  Total emails processed: {emails_processed}")
    print(f"  Emails matched to CSV: {emails_matched}")
    print(f"  Emails not in CSV: {emails_processed - emails_matched}")

    if not comparison_data:
        print("No comparison data generated")
        return

    # Create comparison DataFrame
    comparison_df = pd.DataFrame(comparison_data)

    # Sort by project name (CSV, then mapped, then parsed)
    if len(comparison_df) > 0:
        sort_columns = ["Matched in CSV", "Project Name (CSV)", "Project Name (Mapped)", "Project Name (Parsed)"]
        # Only include columns that exist
        sort_columns = [col for col in sort_columns if col in comparison_df.columns]
        comparison_df = comparison_df.sort_values(
            sort_columns,
            ascending=[False, True, True, True],
            na_position="last",
        )

    # Save to CSV
    output_file = WORKSPACE / "parser_comparison_results.csv"
    comparison_df.to_csv(output_file, index=False)
    print(f"\n✓ Saved comparison results to {output_file}")

    # Print summary statistics (only for matched rows)
    matched_df = comparison_df[comparison_df["Matched in CSV"] == "Yes"]
    if len(matched_df) > 0:
        print("\n" + "=" * 100)
        print("SUMMARY STATISTICS (Matched rows only)")
        print("=" * 100)

        total = len(matched_df)

        print(f"\nTotal matched comparisons: {total}")
        print(f"\nMatch rates:")
        print(
            f"  Project Name: {matched_df['Project Match'].value_counts().get('✓', 0)}/{total} ({100*matched_df['Project Match'].value_counts().get('✓', 0)/total:.1f}%)"
        )
        print(
            f"  LTM EBITDA: {matched_df['EBITDA Match'].value_counts().get('✓', 0)}/{total} ({100*matched_df['EBITDA Match'].value_counts().get('✓', 0)/total:.1f}%)"
        )
        print(
            f"  Source: {matched_df['Source Match'].value_counts().get('✓', 0)}/{total} ({100*matched_df['Source Match'].value_counts().get('✓', 0)/total:.1f}%)"
        )
        print(
            f"  Date Received: {matched_df['Date Match'].value_counts().get('✓', 0)}/{total} ({100*matched_df['Date Match'].value_counts().get('✓', 0)/total:.1f}%)"
        )

        criteria_comparisons = matched_df[matched_df["Criteria Match"] != "N/A"]
        if len(criteria_comparisons) > 0:
            criteria_total = len(criteria_comparisons)
            criteria_matches = criteria_comparisons["Criteria Match"].value_counts().get("✓", 0)
            print(
                f"  Investment Criteria: {criteria_matches}/{criteria_total} ({100*criteria_matches/criteria_total:.1f}%)"
            )

    # Print detailed comparison table (first 30 rows)
    print("\n" + "=" * 100)
    print("DETAILED COMPARISON (first 30 rows)")
    print("=" * 100)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", None)
    pd.set_option("display.max_colwidth", 30)
    print(comparison_df.head(30).to_string(index=False))

    if len(comparison_df) > 30:
        print(f"\n... and {len(comparison_df) - 30} more rows (see {output_file} for full results)")


if __name__ == "__main__":
    main()
