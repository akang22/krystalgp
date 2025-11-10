"""Streamlit page for analyzing individual emails with all parsers."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import io
import os
from datetime import datetime

import pandas as pd
import streamlit as st
from docx import Document
from pdf2image import convert_from_bytes
from PIL import Image

# Load secrets from Streamlit secrets.toml into environment
# This allows parsers to work with st.secrets or .env files
if hasattr(st, "secrets"):
    for key in st.secrets.keys():
        if key not in os.environ:
            os.environ[key] = st.secrets[key]

from email_parser.ensemble_parser import EnsembleParser
from email_parser.layout_attachment_parser import LayoutLLMParser
from email_parser.llm_body_parser import LLMBodyParser
from email_parser.ner_body_parser import NERBodyParser
from email_parser.ocr_attachment_parser import OCRAttachmentParser
from email_parser.ocr_ner_parser import OCRNERParser

# Paths
WORKSPACE = Path(__file__).parent.parent
SAMPLE_EMAILS_DIR = WORKSPACE / "sample_emails"
RESULTS_CSV = WORKSPACE / "results.csv"


@st.cache_resource
def get_parsers():
    """Initialize all parsers (cached)."""
    parsers = {}

    try:
        with st.spinner("Loading NER parser (may take ~30s on first run to download spaCy model)..."):
            parsers["NER Body"] = NERBodyParser()
            st.success("✓ NER Body parser loaded")
    except Exception as e:
        st.warning(f"⚠️ NER parser not available: {str(e)[:200]}")

    try:
        parsers["LLM Body"] = LLMBodyParser()
    except Exception as e:
        st.warning("LLM parser not available (set OPENAI_API_KEY)")

    try:
        parsers["OCR + LLM"] = OCRAttachmentParser()
    except Exception as e:
        st.warning("OCR + LLM parser not available (set OPENAI_API_KEY)")

    try:
        with st.spinner("Loading OCR + NER parser (may take ~30s on first run to download spaCy model)..."):
            parsers["OCR + NER"] = OCRNERParser()
            st.success("✓ OCR + NER parser loaded")
    except Exception as e:
        st.warning(f"⚠️ OCR + NER parser not available: {str(e)[:200]}")

    try:
        parsers["Layout Vision"] = LayoutLLMParser()
    except Exception as e:
        st.warning("Layout Vision parser not available (set OPENAI_API_KEY)")

    try:
        parsers["Final Results"] = EnsembleParser(
            use_llm=True, use_ner=True, use_vision=True, use_ocr=False, results_csv_path=RESULTS_CSV
        )
    except Exception as e:
        st.warning(f"Final Results parser not available: {e}")

    return parsers


def display_email_metadata(email_data):
    """Display email metadata."""
    st.subheader("📧 Email Metadata")

    col1, col2 = st.columns(2)

    with col1:
        st.write("**From:**", email_data.sender or "N/A")
        st.write("**Date:**", str(email_data.date) if email_data.date else "N/A")

    with col2:
        st.write("**To:**", ", ".join(email_data.recipients[:2]) or "N/A")
        if len(email_data.recipients) > 2:
            st.write(f"*... and {len(email_data.recipients) - 2} more*")

    st.write("**Subject:**", email_data.subject or "N/A")


def display_attachments(email_data):
    """Display attachment information."""
    st.subheader("📎 Attachments")

    if not email_data.attachments:
        st.info("No attachments found")
        return

    st.write(f"**Total:** {len(email_data.attachments)} file(s)")

    attachment_data = []
    for att in email_data.attachments:
        attachment_data.append(
            {
                "Filename": att.filename,
                "Type": att.content_type or "Unknown",
                "Size": f"{att.size_bytes / 1024:.1f} KB",
            }
        )

    st.dataframe(pd.DataFrame(attachment_data), width="wide"=True)


def display_email_body(email_data):
    """Display email body."""
    st.subheader("📄 Email Body")

    body = email_data.body_plain or email_data.body_html or ""

    if not body:
        st.info("No body text found")
        return

    # Show first 2000 chars in expander
    with st.expander("View Email Content", expanded=False):
        st.text_area("Body", body, height=300)


def display_parser_results(results):
    """Display results from all parsers."""
    st.subheader("🔍 Parser Results Breakdown")

    # Create comparison table
    comparison_data = []

    for parser_name, result in results.items():
        if result:
            opp = result.opportunity
            comparison_data.append(
                {
                    "Parser": parser_name,
                    "EBITDA": (
                        f"${opp.ebitda_millions:.2f}M" if opp.ebitda_millions else "Not found"
                    ),
                    "Company": opp.company_name or "Not found",
                    "HQ Location": opp.hq_location or "Not found",
                    "Sector": opp.sector or "Not found",
                    "Source": result.extraction_source,
                    "Time (s)": f"{result.processing_time_seconds:.2f}",
                }
            )
        else:
            comparison_data.append(
                {
                    "Parser": parser_name,
                    "EBITDA": "Error",
                    "Company": "Error",
                    "HQ Location": "Error",
                    "Sector": "Error",
                    "Source": "N/A",
                    "Time (s)": "N/A",
                }
            )

    df = pd.DataFrame(comparison_data)
    st.dataframe(df, width="wide"=True, hide_index=True)


def display_confidence_calculation(results):
    """Display ensemble selection logic (NOT averaging)."""
    st.subheader("🎯 Ensemble Selection Logic")

    st.info("**Note:** The ensemble SELECTS the best value, it does NOT average them!")

    # Filter parsers with valid EBITDA
    valid_results = []
    for parser_name, result in results.items():
        if result and result.opportunity.ebitda_millions and parser_name != "Ensemble (Confidence)":
            valid_results.append((parser_name, result))

    if not valid_results:
        st.warning("No valid EBITDA values found")
        return

    # Define weights
    parser_weights = {
        "NER Body": 0.7,
        "LLM Body": 1.0,
        "OCR + LLM": 0.5,
        "OCR + NER": 0.6,
        "Layout Vision": 0.9,
    }

    source_weights = {
        "body": 1.0,
        "attachment": 1.2,
        "both": 1.1,
    }

    raw_text_bonus = 1.1

    # Build calculation table
    calc_data = []
    total_weighted = 0
    total_weight = 0

    for parser_name, result in valid_results:
        opp = result.opportunity
        ebitda = opp.ebitda_millions

        parser_weight = parser_weights.get(parser_name, 0.5)
        source_weight = source_weights.get(result.extraction_source, 1.0)
        has_raw = bool(opp.raw_ebitda_text)

        final_weight = parser_weight * source_weight * (raw_text_bonus if has_raw else 1.0)
        weighted_value = ebitda * final_weight

        calc_data.append(
            {
                "Parser": parser_name,
                "EBITDA": f"${ebitda:.2f}M",
                "Base Weight": parser_weight,
                "Source": result.extraction_source,
                "Source Mult": f"{source_weight}×",
                "Raw Text Bonus": "✓" if has_raw else "✗",
                "Final Weight": f"{final_weight:.3f}",
                "Weighted Value": f"{weighted_value:.3f}",
            }
        )

        total_weighted += weighted_value
        total_weight += final_weight

    # Display calculation table
    st.dataframe(pd.DataFrame(calc_data), width="wide"=True, hide_index=True)

    # Show selection logic
    st.markdown("### 🎯 Selection Logic")

    # Check for fuzzy consensus
    ebitda_values = [result.opportunity.ebitda_millions for _, result in valid_results]

    # Count occurrences (for fuzzy matching)
    from collections import Counter

    value_counts = Counter(ebitda_values)
    most_common = value_counts.most_common(1)[0] if value_counts else (None, 0)

    if most_common[1] >= 2:
        st.success(
            f"""
        ✅ **Fuzzy Consensus Found!**
        
        **${most_common[0]:.2f}M** appears {most_common[1]} times (majority)
        
        → **SELECTED: ${most_common[0]:.2f}M**
        """
        )
    else:
        # Find highest confidence
        best_parser = max(
            valid_results, key=lambda x: calc_data[valid_results.index(x)]["Final Weight"]
        )
        best_ebitda = best_parser[1].opportunity.ebitda_millions
        best_name = best_parser[0]

        st.warning(
            f"""
        ⚠️ **No Consensus - Using Confidence Selection**
        
        Highest confidence: **{best_name}**
        
        → **SELECTED: ${best_ebitda:.2f}M**
        """
        )

    # Show what ensemble returned
    ensemble_result = results.get("Ensemble (Confidence)")
    if ensemble_result and ensemble_result.opportunity.ebitda_millions:
        final_value = ensemble_result.opportunity.ebitda_millions
        method = ensemble_result.opportunity.raw_ebitda_text or "Unknown"

        col1, col2 = st.columns(2)
        with col1:
            st.metric("🎯 Ensemble Selected", f"${final_value:.2f}M")
        with col2:
            st.metric("Selection Method", method.replace("[", "").replace("]", ""))


def display_detailed_results(results):
    """Display detailed results for each parser."""
    st.subheader("📋 Detailed Parser Results")

    for parser_name, result in results.items():
        with st.expander(f"**{parser_name}**"):
            if not result:
                st.error("Parser failed")
                continue

            opp = result.opportunity

            col1, col2 = st.columns(2)

            with col1:
                st.write(
                    "**EBITDA:**",
                    f"${opp.ebitda_millions:.2f}M" if opp.ebitda_millions else "Not found",
                )
                st.write("**Company:**", opp.company_name or "Not found")
                st.write("**HQ Location:**", opp.hq_location or "Not found")
                st.write("**Sector:**", opp.sector or "Not found")

            with col2:
                st.write("**Source Domain:**", opp.source_domain or "Not found")
                st.write("**Recipient:**", opp.recipient or "Not found")
                st.write("**Processing Time:**", f"{result.processing_time_seconds:.2f}s")
                st.write("**Extraction Source:**", result.extraction_source)

            # Show multiple options with confidence scores
            if opp.ebitda_options:
                st.markdown("**💡 EBITDA Options (All Candidates):**")
                ebitda_df = []
                for opt in sorted(opp.ebitda_options, key=lambda x: x.confidence, reverse=True):
                    ebitda_df.append(
                        {
                            "Value": f"${opt.value}M",
                            "Confidence": f"{opt.confidence:.0%}",
                            "Source": opt.source,
                            "Raw Text": opt.raw_text or "N/A",
                        }
                    )
                if ebitda_df:
                    st.dataframe(ebitda_df, width="wide"=True, hide_index=True)

            if opp.location_options:
                st.markdown("**💡 Location Options (All Candidates):**")
                loc_df = []
                for opt in sorted(opp.location_options, key=lambda x: x.confidence, reverse=True):
                    loc_df.append(
                        {
                            "Value": opt.value,
                            "Confidence": f"{opt.confidence:.0%}",
                            "Source": opt.source,
                            "Raw Text": opt.raw_text or "N/A",
                        }
                    )
                if loc_df:
                    st.dataframe(loc_df, width="wide"=True, hide_index=True)

            if opp.company_options:
                st.markdown("**💡 Company Options (All Candidates):**")
                comp_df = []
                for opt in sorted(opp.company_options, key=lambda x: x.confidence, reverse=True):
                    comp_df.append(
                        {
                            "Value": opt.value,
                            "Confidence": f"{opt.confidence:.0%}",
                            "Source": opt.source,
                            "Raw Text": opt.raw_text or "N/A",
                        }
                    )
                if comp_df:
                    st.dataframe(comp_df, width="wide"=True, hide_index=True)

            if opp.raw_ebitda_text and not opp.ebitda_options:
                st.write("**Raw EBITDA Text:**")
                st.code(opp.raw_ebitda_text)


def display_pdf_attachment(attachment):
    """Display PDF attachment."""
    try:
        # Convert PDF to images
        images = convert_from_bytes(attachment.content, dpi=150)

        st.markdown(f"**{attachment.filename}** ({attachment.size_bytes / 1024:.1f} KB)")

        # Display first 3 pages
        for i, img in enumerate(images[:3]):
            st.image(img, caption=f"Page {i+1}", use_column_width=True)

        if len(images) > 3:
            st.info(f"Showing first 3 pages of {len(images)} total pages")

    except Exception as e:
        st.error(f"Failed to display PDF: {e}")


def display_image_attachment(attachment):
    """Display image attachment."""
    try:
        image = Image.open(io.BytesIO(attachment.content))
        st.markdown(f"**{attachment.filename}** ({attachment.size_bytes / 1024:.1f} KB)")
        st.image(image, use_column_width=True)
    except Exception as e:
        st.error(f"Failed to display image: {e}")


def display_docx_attachment(attachment):
    """Display Word document as text."""
    try:
        doc = Document(io.BytesIO(attachment.content))
        st.markdown(f"**{attachment.filename}** ({attachment.size_bytes / 1024:.1f} KB)")

        # Extract all text
        full_text = []
        for para in doc.paragraphs:
            if para.text.strip():
                full_text.append(para.text)

        # Also extract from tables
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text for cell in row.cells)
                if row_text.strip():
                    full_text.append(row_text)

        text_content = "\n\n".join(full_text)

        if text_content:
            st.text_area("Document Content", text_content, height=400, label_visibility="collapsed")
        else:
            st.warning("No text content found in document")

    except Exception as e:
        st.error(f"Failed to display Word document: {e}")


def display_text_attachment(attachment):
    """Display text-based attachments."""
    try:
        # Try to decode as text
        text_content = attachment.content.decode("utf-8", errors="ignore")

        st.markdown(f"**{attachment.filename}** ({attachment.size_bytes / 1024:.1f} KB)")
        st.text_area(
            "File Content",
            text_content[:5000],  # First 5000 chars
            height=300,
            label_visibility="collapsed",
        )

        if len(text_content) > 5000:
            st.info(f"Showing first 5000 characters of {len(text_content)} total")

    except Exception as e:
        st.error(f"Failed to display text file: {e}")


def display_attachments_visual(email_data):
    """Display attachments with preview."""
    st.subheader("📎 Attachments")

    if not email_data.attachments:
        st.info("No attachments found")
        return

    st.write(f"**Total:** {len(email_data.attachments)} file(s)")

    # Display each attachment
    for att in email_data.attachments:
        filename_lower = att.filename.lower()

        with st.expander(f"📄 {att.filename} ({att.size_bytes / 1024:.1f} KB)"):
            if filename_lower.endswith(".pdf"):
                display_pdf_attachment(att)
            elif any(
                filename_lower.endswith(ext)
                for ext in [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff"]
            ):
                display_image_attachment(att)
            elif filename_lower.endswith(".docx") or filename_lower.endswith(".doc"):
                display_docx_attachment(att)
            elif any(filename_lower.endswith(ext) for ext in [".txt", ".csv", ".log", ".md"]):
                display_text_attachment(att)
            else:
                # Try to display as text
                st.info(f"Type: {att.content_type or 'Unknown'}")
                try:
                    display_text_attachment(att)
                except:
                    st.warning("Preview not available for this file type")


def main():
    """Main Streamlit app."""
    # Get list of emails
    email_files = sorted([f.name for f in SAMPLE_EMAILS_DIR.glob("*.msg")])

    if not email_files:
        st.error(f"No .msg files found in {SAMPLE_EMAILS_DIR}")
        return

    # Email selector in main page
    st.subheader("📨 Select Email to Analyze")

    # Add upload option
    col1, col2 = st.columns([3, 1])

    with col1:
        selected_email = st.selectbox(
            "Choose an email:",
            email_files,
            index=(
                email_files.index(
                    "FW Project Gravy - Franchise QSR Portfolio Acquisition Opportunity.msg"
                )
                if "FW Project Gravy - Franchise QSR Portfolio Acquisition Opportunity.msg"
                in email_files
                else 0
            ),
            label_visibility="collapsed",
        )

    with col2:
        uploaded_file = st.file_uploader(
            "Or upload",
            type=["msg"],
            label_visibility="visible",
            help="Upload a .msg file to analyze",
        )

    # Handle uploaded file
    if uploaded_file is not None:
        # Save to sample_emails directory
        save_path = SAMPLE_EMAILS_DIR / uploaded_file.name

        with open(save_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        st.success(f"✅ Uploaded and saved: {uploaded_file.name}")
        st.info("Refresh the page to see it in the dropdown, or continue analyzing below.")

        email_path = save_path
        selected_email = uploaded_file.name
    else:
        email_path = SAMPLE_EMAILS_DIR / selected_email

    st.divider()

    # Initialize parsers
    parsers = get_parsers()

    if not parsers:
        st.error("No parsers available. Check your configuration.")
        return

    # Parse email
    with st.spinner("Parsing email..."):
        # Get email metadata first
        try:
            first_parser = list(parsers.values())[0]
            email_data = first_parser.extract_msg_file(email_path)
        except Exception as e:
            st.error(f"Failed to read email: {e}")
            return

        # Display email info
        display_email_metadata(email_data)

        st.divider()

        # Attachments with visual display
        display_attachments_visual(email_data)

        st.divider()

        # Email body
        display_email_body(email_data)

        st.divider()

        # Run all parsers
        results = {}

        progress_bar = st.progress(0)
        status_text = st.empty()

        error_log = []

        for idx, (parser_name, parser) in enumerate(parsers.items()):
            status_text.text(f"Running {parser_name}...")

            try:
                result = parser.parse(email_path)
                results[parser_name] = result

                # Debug: show what was extracted
                if result and result.opportunity:
                    opp = result.opportunity
                    ebitda_str = f"${opp.ebitda_millions:.2f}M" if opp.ebitda_millions else "None"
                    status_text.text(
                        f"✓ {parser_name}: EBITDA={ebitda_str}, Company={opp.company_name or 'None'}"
                    )

                    # Log errors if any
                    if result.errors:
                        error_log.append(f"{parser_name}: {', '.join(result.errors)}")

            except Exception as e:
                error_msg = f"{parser_name} failed: {str(e)}"
                error_log.append(error_msg)
                st.error(f"❌ {error_msg}")
                results[parser_name] = None

            progress_bar.progress((idx + 1) / len(parsers))

        status_text.text("✅ Parsing complete!")

        # Show errors if any
        if error_log:
            with st.expander("⚠️ Errors/Warnings"):
                for err in error_log:
                    st.warning(err)

        status_text.text("✅ Parsing complete!")
        progress_bar.empty()
        status_text.empty()

    # Display results
    display_parser_results(results)

    st.divider()

    # Detailed results
    display_detailed_results(results)

    # Download results
    st.divider()
    st.subheader("💾 Export Results")

    # Prepare export data
    export_data = []
    for parser_name, result in results.items():
        if result:
            opp = result.opportunity
            export_data.append(
                {
                    "Parser": parser_name,
                    "EBITDA_millions": opp.ebitda_millions,
                    "Company": opp.company_name,
                    "HQ_Location": opp.hq_location,
                    "Sector": opp.sector,
                    "Source_Domain": opp.source_domain,
                    "Recipient": opp.recipient,
                    "Raw_EBITDA_Text": opp.raw_ebitda_text,
                    "Processing_Time_s": result.processing_time_seconds,
                    "Extraction_Source": result.extraction_source,
                }
            )

    if export_data:
        df_export = pd.DataFrame(export_data)
        csv = df_export.to_csv(index=False)

        st.download_button(
            label="📥 Download Results as CSV",
            data=csv,
            file_name=f"parser_results_{selected_email.replace('.msg', '')}.csv",
            mime="text/csv",
        )


if __name__ == "__main__":
    main()
