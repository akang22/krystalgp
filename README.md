# Email Parser for Investment Opportunities

A comprehensive email parser system for extracting structured investment opportunity data from .msg email files and their attachments. This project compares multiple parsing approaches including LLM-based, NER-based, and OCR+Layout-aware methods.

## Features

- **Multiple Parsing Approaches**:
  - LLM-based body parsing (OpenAI GPT-4)
  - NER + Regex body parsing (spaCy)
  - OCR + LLM for PDF attachments
  - Layout-aware LLM for PDF attachments (LayoutLMv3/GPT-4-Vision)

- **Extracted Fields**:
  - Source (email domain)
  - Recipient (Krystal GP member)
  - HQ Location
  - EBITDA (in millions)
  - Date/timestamp
  - Bounding boxes for source visualization

- **Interactive Dashboard**:
  - Side-by-side comparison of parsing approaches
  - Accuracy metrics and performance analysis
  - Visual bounding box overlay on original documents
  - Batch processing capabilities

## Installation

### Prerequisites

- Python 3.10 or higher
- [UV package manager](https://github.com/astral-sh/uv)
- Tesseract OCR (for OCR-based parsing)
- Poppler (for PDF to image conversion)

### macOS Installation

```bash
# Install system dependencies
brew install tesseract poppler

# Install UV (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository
cd /Users/yanjunk/projects/krystalgp

# Install Python dependencies
uv sync

# Download spaCy language model
uv run python -m spacy download en_core_web_trf
```

### Environment Setup

Create a `.env` file in the project root:

```bash
# OpenAI API key for LLM-based parsing
OPENAI_API_KEY=your_api_key_here

# Optional: HuggingFace token for models
HF_TOKEN=your_token_here
```

## Project Structure

```
krystalgp/
├── .cursorrules              # Software engineering guidelines
├── .gitignore
├── pyproject.toml            # UV configuration
├── README.md                 # This file
├── src/email_parser/
│   ├── __init__.py
│   ├── base.py              # Base parser and Pydantic models
│   ├── llm_body_parser.py   # Approach 1: LLM for body
│   ├── ner_body_parser.py   # Approach 2: NER for body
│   ├── ocr_attachment_parser.py   # OCR + LLM for attachments
│   ├── layout_attachment_parser.py # Layout-aware for attachments
│   └── utils.py             # Helper functions
├── tests/
│   ├── __init__.py
│   ├── test_parsers.py      # Main test suite
│   └── fixtures/            # Test data
├── data/
│   ├── ground_truth_labels.csv
│   └── comparison_results.csv
├── sample_emails/           # Input .msg files
├── results.csv              # Reference EBITDA data
├── streamlit_app.py         # Main dashboard
└── notebooks/               # Exploratory analysis
```

## Usage

### Running Parsers Programmatically

```python
from email_parser.llm_body_parser import LLMBodyParser
from email_parser.ocr_attachment_parser import OCRAttachmentParser

# Initialize parsers
llm_parser = LLMBodyParser()
ocr_parser = OCRAttachmentParser()

# Parse an email
email_path = "sample_emails/Project Aberdeen - Krystal Growth Partners .msg"
result = llm_parser.parse(email_path)

print(f"EBITDA: ${result.ebitda}M")
print(f"HQ Location: {result.hq_location}")
```

### Running the Streamlit Dashboard

```bash
uv run streamlit run streamlit_app.py
```

Navigate to `http://localhost:8501` to view the dashboard.

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage report
uv run pytest --cov=src --cov-report=html

# Run specific test file
uv run pytest tests/test_parsers.py
```

## Parsing Approaches

### 1. LLM Body Parser
Uses OpenAI's GPT-4 to extract structured data from email body text. Provides high accuracy for natural language understanding but requires API calls.

### 2. NER Body Parser
Uses spaCy's Named Entity Recognition combined with regex patterns. Fast and works offline, but may miss context-dependent information.

### 3. OCR + LLM Attachment Parser
Converts PDF attachments to images, applies OCR, then uses LLM for extraction. Best for scanned documents or PDFs without text layer.

### 4. Layout-Aware Attachment Parser
Uses specialized document understanding models (LayoutLMv3) or vision models (GPT-4-Vision) to understand document structure and layout. Best for structured documents like teasers and pitch decks.

## Evaluation Metrics

The system evaluates parsers on:
- **Exact Match Accuracy**: Percentage of exact matches with ground truth
- **Fuzzy Match Accuracy**: Percentage of semantically similar matches
- **EBITDA Precision/Recall**: Accuracy of financial figure extraction
- **Processing Time**: Average time per email
- **Field Coverage**: Percentage of fields successfully extracted

## Development

### Code Quality

This project follows strict software engineering practices:
- Type hints on all functions
- Google-style docstrings
- >80% test coverage
- Automated linting with ruff and black
- Small, focused commits

See `.cursorrules` for detailed guidelines.

### Contributing

1. Create a feature branch
2. Make focused commits
3. Add tests for new features
4. Run tests and linting before committing
5. Submit pull request

## License

MIT License

## Contact

Krystal Growth Partners

