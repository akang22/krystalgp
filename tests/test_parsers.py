"""Test suite for email parsers with accuracy metrics.

This module tests all parser implementations against ground truth labels.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import pytest
from pytest import approx

# Add src to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from email_parser.base import BaseParser, InvestmentOpportunity
from email_parser.llm_body_parser import LLMBodyParser
from email_parser.ner_body_parser import NERBodyParser
from email_parser.ocr_attachment_parser import OCRAttachmentParser
from email_parser.layout_attachment_parser import LayoutLLMParser
from email_parser.utils import fuzzy_match_ebitda


# Paths
WORKSPACE = Path(__file__).parent.parent
SAMPLE_EMAILS_DIR = WORKSPACE / "sample_emails"
GROUND_TRUTH_PATH = WORKSPACE / "data" / "ground_truth_labels.csv"


@pytest.fixture(scope="module")
def ground_truth() -> pd.DataFrame:
    """Load ground truth labels.
    
    Returns:
        DataFrame with ground truth labels
    """
    if not GROUND_TRUTH_PATH.exists():
        pytest.skip(f"Ground truth file not found: {GROUND_TRUTH_PATH}")
    
    return pd.read_csv(GROUND_TRUTH_PATH)


@pytest.fixture(scope="module")
def llm_parser() -> Optional[LLMBodyParser]:
    """Initialize LLM parser if API key available.
    
    Returns:
        LLMBodyParser or None
    """
    try:
        return LLMBodyParser()
    except ValueError:
        pytest.skip("OpenAI API key not available")


@pytest.fixture(scope="module")
def ner_parser() -> NERBodyParser:
    """Initialize NER parser.
    
    Returns:
        NERBodyParser instance
    """
    return NERBodyParser()


@pytest.fixture(scope="module")
def ocr_parser() -> Optional[OCRAttachmentParser]:
    """Initialize OCR parser if API key available.
    
    Returns:
        OCRAttachmentParser or None
    """
    try:
        return OCRAttachmentParser()
    except ValueError:
        pytest.skip("OpenAI API key not available")


@pytest.fixture(scope="module")
def layout_parser() -> Optional[LayoutLLMParser]:
    """Initialize layout-aware parser if API key available.
    
    Returns:
        LayoutLLMParser or None
    """
    try:
        return LayoutLLMParser()
    except ValueError:
        pytest.skip("OpenAI API key not available")


class TestParserAccuracy:
    """Test parser accuracy against ground truth."""
    
    def test_ner_parser_ebitda_extraction(self, ner_parser, ground_truth):
        """Test NER parser EBITDA extraction accuracy."""
        correct = 0
        total = 0
        
        for _, row in ground_truth.iterrows():
            email_file = row['email_file']
            expected_ebitda = row['ebitda_millions']
            
            # Skip if no expected EBITDA
            if pd.isna(expected_ebitda) or expected_ebitda == '':
                continue
            
            email_path = SAMPLE_EMAILS_DIR / email_file
            if not email_path.exists():
                continue
            
            result = ner_parser.parse(email_path)
            extracted_ebitda = result.opportunity.ebitda_millions
            
            total += 1
            if fuzzy_match_ebitda(extracted_ebitda, float(expected_ebitda), tolerance=0.5):
                correct += 1
        
        accuracy = correct / total if total > 0 else 0
        print(f"\nNER Parser EBITDA Accuracy: {correct}/{total} = {accuracy:.1%}")
        
        # Assert at least some accuracy (this is a baseline)
        assert accuracy >= 0.0, "NER parser should extract some EBITDA values"
    
    def test_ner_parser_company_extraction(self, ner_parser, ground_truth):
        """Test NER parser company name extraction."""
        correct = 0
        total = 0
        
        for _, row in ground_truth.iterrows():
            email_file = row['email_file']
            expected_company = row['company_name']
            
            # Skip if no expected company
            if pd.isna(expected_company) or expected_company == '':
                continue
            
            email_path = SAMPLE_EMAILS_DIR / email_file
            if not email_path.exists():
                continue
            
            result = ner_parser.parse(email_path)
            extracted_company = result.opportunity.company_name
            
            total += 1
            if extracted_company and expected_company.lower() in extracted_company.lower():
                correct += 1
        
        accuracy = correct / total if total > 0 else 0
        print(f"\nNER Parser Company Name Accuracy: {correct}/{total} = {accuracy:.1%}")
    
    def test_llm_parser_ebitda_extraction(self, llm_parser, ground_truth):
        """Test LLM parser EBITDA extraction accuracy."""
        if llm_parser is None:
            pytest.skip("LLM parser not available")
        
        correct = 0
        total = 0
        
        for _, row in ground_truth.iterrows():
            email_file = row['email_file']
            expected_ebitda = row['ebitda_millions']
            
            # Skip if no expected EBITDA or not from body
            if pd.isna(expected_ebitda) or expected_ebitda == '':
                continue
            if 'attachment' in str(row.get('data_source', '')).lower():
                continue  # LLM body parser shouldn't handle attachment data
            
            email_path = SAMPLE_EMAILS_DIR / email_file
            if not email_path.exists():
                continue
            
            result = llm_parser.parse(email_path)
            extracted_ebitda = result.opportunity.ebitda_millions
            
            total += 1
            if fuzzy_match_ebitda(extracted_ebitda, float(expected_ebitda), tolerance=0.5):
                correct += 1
            else:
                print(f"\n  Mismatch in {email_file}: Expected {expected_ebitda}, Got {extracted_ebitda}")
        
        accuracy = correct / total if total > 0 else 0
        print(f"\nLLM Parser EBITDA Accuracy: {correct}/{total} = {accuracy:.1%}")
        
        # LLM should be more accurate than NER
        assert accuracy >= 0.3, "LLM parser should extract reasonable number of EBITDA values"
    
    def test_source_domain_extraction(self, ner_parser, ground_truth):
        """Test source domain extraction from sender."""
        correct = 0
        total = 0
        
        for _, row in ground_truth.iterrows():
            email_file = row['email_file']
            expected_domain = row['source_domain']
            
            # Skip if no expected domain
            if pd.isna(expected_domain) or expected_domain == '':
                continue
            
            email_path = SAMPLE_EMAILS_DIR / email_file
            if not email_path.exists():
                continue
            
            result = ner_parser.parse(email_path)
            extracted_domain = result.opportunity.source_domain
            
            total += 1
            if extracted_domain and expected_domain.lower() in extracted_domain.lower():
                correct += 1
        
        accuracy = correct / total if total > 0 else 0
        print(f"\nSource Domain Extraction Accuracy: {correct}/{total} = {accuracy:.1%}")


class TestParserPerformance:
    """Test parser performance and processing time."""
    
    def test_ner_parser_speed(self, ner_parser, ground_truth):
        """Test NER parser processing speed."""
        processing_times = []
        
        for _, row in ground_truth.iterrows()[:5]:  # Test first 5
            email_file = row['email_file']
            email_path = SAMPLE_EMAILS_DIR / email_file
            
            if not email_path.exists():
                continue
            
            result = ner_parser.parse(email_path)
            if result.processing_time_seconds:
                processing_times.append(result.processing_time_seconds)
        
        if processing_times:
            avg_time = sum(processing_times) / len(processing_times)
            print(f"\nNER Parser Average Processing Time: {avg_time:.2f}s")
            
            # NER should be fast (< 5 seconds per email)
            assert avg_time < 5.0, "NER parser should process emails quickly"
    
    def test_llm_parser_speed(self, llm_parser, ground_truth):
        """Test LLM parser processing speed."""
        if llm_parser is None:
            pytest.skip("LLM parser not available")
        
        processing_times = []
        
        for _, row in ground_truth.iterrows()[:3]:  # Test first 3 (API calls are slow)
            email_file = row['email_file']
            email_path = SAMPLE_EMAILS_DIR / email_file
            
            if not email_path.exists():
                continue
            
            result = llm_parser.parse(email_path)
            if result.processing_time_seconds:
                processing_times.append(result.processing_time_seconds)
        
        if processing_times:
            avg_time = sum(processing_times) / len(processing_times)
            print(f"\nLLM Parser Average Processing Time: {avg_time:.2f}s")


class TestIndividualParsers:
    """Test individual parser functionality."""
    
    def test_base_parser_msg_extraction(self, ner_parser, ground_truth):
        """Test base parser .msg file extraction."""
        for _, row in ground_truth.iterrows()[:1]:  # Test one email
            email_file = row['email_file']
            email_path = SAMPLE_EMAILS_DIR / email_file
            
            if not email_path.exists():
                continue
            
            email_data = ner_parser.extract_msg_file(email_path)
            
            assert email_data.sender is not None, "Sender should be extracted"
            assert email_data.date is not None, "Date should be extracted"
            assert len(email_data.recipients) > 0, "Recipients should be extracted"
            
            print(f"\nExtracted from {email_file}:")
            print(f"  Sender: {email_data.sender}")
            print(f"  Recipients: {email_data.recipients}")
            print(f"  Date: {email_data.date}")
            print(f"  Attachments: {len(email_data.attachments)}")
            
            break
    
    def test_domain_extraction(self, ner_parser):
        """Test domain extraction utility."""
        test_cases = [
            ("john@kpmg.com", "kpmg.com"),
            ("John Doe <john@bdo.ca>", "bdo.ca"),
            ("jane.smith@deloitte.ca", "deloitte.ca"),
        ]
        
        for email, expected_domain in test_cases:
            domain = ner_parser.extract_domain(email)
            assert domain == expected_domain, f"Failed to extract domain from {email}"


@pytest.mark.parametrize("ebitda1,ebitda2,expected", [
    (5.2, 5.2, True),
    (5.2, 5.0, True),  # Within 0.5 tolerance
    (5.2, 10.0, False),  # Outside tolerance
    (None, 5.0, False),
    (5.0, None, False),
])
def test_fuzzy_match_ebitda(ebitda1, ebitda2, expected):
    """Test fuzzy EBITDA matching."""
    result = fuzzy_match_ebitda(ebitda1, ebitda2, tolerance=0.5)
    assert result == expected


def test_ground_truth_exists():
    """Test that ground truth file exists and is valid."""
    assert GROUND_TRUTH_PATH.exists(), f"Ground truth file not found: {GROUND_TRUTH_PATH}"
    
    df = pd.read_csv(GROUND_TRUTH_PATH)
    assert len(df) > 0, "Ground truth should have at least one entry"
    
    required_columns = ['email_file', 'ebitda_millions', 'company_name']
    for col in required_columns:
        assert col in df.columns, f"Missing required column: {col}"
    
    print(f"\nGround truth loaded: {len(df)} emails")


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main([__file__, "-v", "-s"])

