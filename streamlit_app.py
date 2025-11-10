"""Streamlit Email Analyzer for investment opportunity parsing.

Interactive tool to analyze emails with all parser approaches.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

import io
import os
import base64
import pandas as pd
import streamlit as st
from pdf2image import convert_from_bytes
from PIL import Image

# Load secrets from Streamlit secrets.toml into environment
# This allows parsers to work with st.secrets or .env files
if hasattr(st, 'secrets'):
    for key in st.secrets.keys():
        if key not in os.environ:
            os.environ[key] = st.secrets[key]

from email_parser.llm_body_parser import LLMBodyParser
from email_parser.ner_body_parser import NERBodyParser
from email_parser.ocr_attachment_parser import OCRAttachmentParser
from email_parser.ocr_ner_parser import OCRNERParser
from email_parser.layout_attachment_parser import LayoutLLMParser
from email_parser.ensemble_parser import EnsembleParser
from email_parser.utils import fuzzy_match_ebitda


# Configuration
st.set_page_config(
    page_title="Email Parser Comparison",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Paths
WORKSPACE = Path(__file__).parent
SAMPLE_EMAILS_DIR = WORKSPACE / "sample_emails"
GROUND_TRUTH_PATH = WORKSPACE / "data" / "ground_truth_labels.csv"
RESULTS_PATH = WORKSPACE / "results.csv"


def load_ground_truth():
    """Load ground truth labels."""
    if GROUND_TRUTH_PATH.exists():
        return pd.read_csv(GROUND_TRUTH_PATH)
    return None


def load_results():
    """Load results.csv for reference."""
    if RESULTS_PATH.exists():
        return pd.read_csv(RESULTS_PATH)
    return None


@st.cache_resource
def get_parsers():
    """Initialize all parsers (cached)."""
    parsers = {}
    
    # NER parser (always available)
    try:
        parsers['NER Body'] = NERBodyParser()
    except Exception as e:
        st.warning(f"Failed to initialize NER parser: {e}")
    
    # LLM parsers (require API key)
    try:
        parsers['LLM Body'] = LLMBodyParser()
    except ValueError as e:
        st.info("LLM Body parser not available. Set OPENAI_API_KEY to enable.")
    
    try:
        parsers['OCR + LLM Attachment'] = OCRAttachmentParser()
    except ValueError:
        st.info("OCR Attachment parser not available. Set OPENAI_API_KEY to enable.")
    
    try:
        parsers['Layout LLM Attachment'] = LayoutLLMParser()
    except ValueError:
        st.info("Layout LLM parser not available. Set OPENAI_API_KEY to enable.")
    
    return parsers


def page_comparison():
    """Page 1: Parser Approach Comparison."""
    st.title("📊 Parser Approach Comparison")
    st.markdown("Compare accuracy and performance of different parsing approaches.")
    
    ground_truth = load_ground_truth()
    
    if ground_truth is None:
        st.error(f"Ground truth file not found: {GROUND_TRUTH_PATH}")
        return
    
    st.subheader("Ground Truth Dataset")
    st.write(f"Total emails in ground truth: **{len(ground_truth)}**")
    st.dataframe(ground_truth, width="wide")
    
    # Accuracy metrics section
    st.subheader("Accuracy Metrics")
    
    parsers = get_parsers()
    
    if not parsers:
        st.warning("No parsers available. Check your configuration.")
        return
    
    # Calculate accuracy for each parser
    results_data = []
    
    for parser_name, parser in parsers.items():
        st.write(f"**Testing {parser_name}...**")
        
        correct_ebitda = 0
        total_ebitda = 0
        correct_company = 0
        total_company = 0
        processing_times = []
        
        progress_bar = st.progress(0)
        
        for idx, row in ground_truth.iterrows():
            email_file = row['email_file']
            email_path = SAMPLE_EMAILS_DIR / email_file
            
            if not email_path.exists():
                continue
            
            # Parse email
            try:
                result = parser.parse(email_path)
                opportunity = result.opportunity
                
                # Check EBITDA
                expected_ebitda = row['ebitda_millions']
                if not pd.isna(expected_ebitda) and expected_ebitda != '':
                    total_ebitda += 1
                    if fuzzy_match_ebitda(
                        opportunity.ebitda_millions,
                        float(expected_ebitda),
                        tolerance=0.5
                    ):
                        correct_ebitda += 1
                
                # Check company name
                expected_company = row['company_name']
                if not pd.isna(expected_company) and expected_company != '':
                    total_company += 1
                    if opportunity.company_name and \
                       expected_company.lower() in opportunity.company_name.lower():
                        correct_company += 1
                
                # Track processing time
                if result.processing_time_seconds:
                    processing_times.append(result.processing_time_seconds)
                
            except Exception as e:
                st.warning(f"Error parsing {email_file}: {e}")
            
            progress_bar.progress((idx + 1) / len(ground_truth))
        
        # Calculate metrics
        ebitda_accuracy = correct_ebitda / total_ebitda if total_ebitda > 0 else 0
        company_accuracy = correct_company / total_company if total_company > 0 else 0
        avg_time = sum(processing_times) / len(processing_times) if processing_times else 0
        
        results_data.append({
            'Parser': parser_name,
            'EBITDA Accuracy': f"{ebitda_accuracy:.1%}",
            'Company Accuracy': f"{company_accuracy:.1%}",
            'Avg Processing Time (s)': f"{avg_time:.2f}",
            'Total Emails': len(ground_truth),
        })
    
    # Display results table
    results_df = pd.DataFrame(results_data)
    st.dataframe(results_df, width="wide")
    
    # Visualization
    st.subheader("Performance Comparison")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.bar_chart(
            results_df.set_index('Parser')[['EBITDA Accuracy']].applymap(
                lambda x: float(x.strip('%')) / 100
            )
        )
    
    with col2:
        st.bar_chart(
            results_df.set_index('Parser')[['Company Accuracy']].applymap(
                lambda x: float(x.strip('%')) / 100
            )
        )


def page_side_by_side():
    """Page 2: Side-by-Side Email Viewer."""
    st.title("📧 Side-by-Side Email Viewer")
    st.markdown("View original email and extracted data side-by-side.")
    
    # Email selector
    ground_truth = load_ground_truth()
    
    if ground_truth is None:
        st.error("Ground truth file not found.")
        return
    
    email_files = ground_truth['email_file'].tolist()
    selected_email = st.selectbox("Select Email", email_files)
    
    if not selected_email:
        return
    
    email_path = SAMPLE_EMAILS_DIR / selected_email
    
    if not email_path.exists():
        st.error(f"Email file not found: {email_path}")
        return
    
    # Get ground truth for this email
    gt_row = ground_truth[ground_truth['email_file'] == selected_email].iloc[0]
    
    # Display ground truth
    st.subheader("Ground Truth")
    col1, col2, col3 = st.columns(3)
    col1.metric("EBITDA", f"${gt_row['ebitda_millions']}M" if not pd.isna(gt_row['ebitda_millions']) else "N/A")
    col2.metric("Company", gt_row['company_name'] if not pd.isna(gt_row['company_name']) else "N/A")
    col3.metric("Sector", gt_row['sector'] if not pd.isna(gt_row['sector']) else "N/A")
    
    # Parse with all available parsers
    st.subheader("Parser Results")
    
    parsers = get_parsers()
    
    for parser_name, parser in parsers.items():
        with st.expander(f"**{parser_name}**"):
            try:
                result = parser.parse(email_path)
                opportunity = result.opportunity
                
                col1, col2, col3, col4 = st.columns(4)
                
                col1.metric(
                    "EBITDA",
                    f"${opportunity.ebitda_millions}M" if opportunity.ebitda_millions else "N/A"
                )
                col2.metric("Company", opportunity.company_name or "N/A")
                col3.metric("HQ Location", opportunity.hq_location or "N/A")
                col4.metric("Processing Time", f"{result.processing_time_seconds:.2f}s")
                
                st.write("**Additional Fields:**")
                st.json({
                    "source_domain": opportunity.source_domain,
                    "recipient": opportunity.recipient,
                    "sector": opportunity.sector,
                    "raw_ebitda_text": opportunity.raw_ebitda_text,
                    "date": str(opportunity.date) if opportunity.date else None,
                })
                
            except Exception as e:
                st.error(f"Error: {e}")


def page_batch_processing():
    """Page 3: Batch Processing."""
    st.title("⚙️ Batch Processing")
    st.markdown("Process multiple emails and download results.")
    
    st.subheader("Settings")
    
    # Parser selection
    parsers = get_parsers()
    parser_names = list(parsers.keys())
    
    selected_parsers = st.multiselect(
        "Select Parsers",
        parser_names,
        default=parser_names[:1] if parser_names else []
    )
    
    # Email selection
    ground_truth = load_ground_truth()
    
    if ground_truth is None:
        st.warning("Ground truth file not found. Processing all emails in sample_emails/")
        email_files = [f.name for f in SAMPLE_EMAILS_DIR.glob("*.msg")]
    else:
        email_files = ground_truth['email_file'].tolist()
    
    num_emails = st.slider("Number of emails to process", 1, len(email_files), min(10, len(email_files)))
    
    # Process button
    if st.button("Start Batch Processing"):
        if not selected_parsers:
            st.error("Please select at least one parser.")
            return
        
        st.subheader("Processing Results")
        
        all_results = []
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for idx, email_file in enumerate(email_files[:num_emails]):
            status_text.text(f"Processing {email_file}...")
            email_path = SAMPLE_EMAILS_DIR / email_file
            
            if not email_path.exists():
                continue
            
            row_data = {'email_file': email_file}
            
            for parser_name in selected_parsers:
                parser = parsers[parser_name]
                
                try:
                    result = parser.parse(email_path)
                    opp = result.opportunity
                    
                    row_data[f'{parser_name}_ebitda'] = opp.ebitda_millions
                    row_data[f'{parser_name}_company'] = opp.company_name
                    row_data[f'{parser_name}_location'] = opp.hq_location
                    row_data[f'{parser_name}_source'] = opp.source_domain
                    row_data[f'{parser_name}_time'] = result.processing_time_seconds
                    
                except Exception as e:
                    row_data[f'{parser_name}_error'] = str(e)
            
            all_results.append(row_data)
            progress_bar.progress((idx + 1) / num_emails)
        
        # Display results
        results_df = pd.DataFrame(all_results)
        st.dataframe(results_df, width="wide")
        
        # Download button
        csv = results_df.to_csv(index=False)
        st.download_button(
            label="Download Results CSV",
            data=csv,
            file_name="batch_processing_results.csv",
            mime="text/csv",
        )
        
        status_text.text("✅ Processing complete!")


def main():
    """Main app - Email Analyzer only."""
    st.title("📧 Email Parser - Investment Opportunity Analyzer")
    st.markdown("Analyze investment opportunity emails with multiple parsing approaches.")
    
    # Import and run email analyzer directly
    from streamlit_pages.email_analyzer import main as email_analyzer_main
    email_analyzer_main()


if __name__ == "__main__":
    main()


