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

### Quick Start

1. **Set up your environment variables (optional):**

```bash
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY (only needed for LLM parsers)
```

**Note**: The NER Body Parser works without any API keys!

2. **Download spaCy model:**

```bash
# Use uv pip to install the spaCy model directly
uv pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl
```

3. **Run the Streamlit dashboard:**

```bash
uv run streamlit run streamlit_app.py
```

Navigate to `http://localhost:8501` to view the dashboard.

### Running Parsers Programmatically

```python
from pathlib import Path
from email_parser.llm_body_parser import LLMBodyParser
from email_parser.ner_body_parser import NERBodyParser
from email_parser.ocr_attachment_parser import OCRAttachmentParser

# Initialize parsers
llm_parser = LLMBodyParser()  # Requires OPENAI_API_KEY
ner_parser = NERBodyParser()  # No API key needed
ocr_parser = OCRAttachmentParser()  # Requires OPENAI_API_KEY

# Parse an email
email_path = Path("sample_emails/Project Aberdeen - Krystal Growth Partners .msg")
result = llm_parser.parse(email_path)

# Access extracted data
opportunity = result.opportunity
print(f"Source: {opportunity.source_domain}")
print(f"Recipient: {opportunity.recipient}")
print(f"EBITDA: ${opportunity.ebitda_millions}M")
print(f"HQ Location: {opportunity.hq_location}")
print(f"Company: {opportunity.company_name}")
print(f"Processing Time: {result.processing_time_seconds:.2f}s")
```

### Running Full Evaluation

Run all parsers on the entire dataset and generate comparison metrics:

```bash
uv run python scripts/run_evaluation.py
```

This will:
- Process all emails in `ground_truth_labels.csv`
- Run all available parsers
- Generate accuracy metrics
- Save results to `data/comparison_results.csv`

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage report
uv run pytest --cov=src --cov-report=html

# Run specific test file
uv run pytest tests/test_parsers.py -v

# Run tests without API calls (skip LLM tests)
uv run pytest -m "not requires_api"
```

### Creating Ground Truth Labels

To add more ground truth labels:

```bash
# Run helper script (requires API key)
uv run python scripts/create_ground_truth.py

# Manually edit data/ground_truth_labels.csv
# Verify EBITDA values against results.csv and source documents
```

## Parsing Approaches

The system combines **body parsers** (for email text) with **attachment parsers** (for PDF/images):

### Body Parsers

#### 1. LLM Body Parser (`llm_body_parser.py`)
- **Method**: OpenAI GPT-4 with structured JSON output
- **Pros**: High accuracy, understands context and nuance
- **Cons**: Requires API key, slower, costs per email
- **Best for**: Complex email body text with varied formats

#### 2. NER Body Parser (`ner_body_parser.py`)
- **Method**: spaCy NER + regex patterns
- **Pros**: Fast, works offline, no API costs
- **Cons**: Lower accuracy, struggles with complex patterns
- **Best for**: Baseline comparison, high-volume processing

### Attachment Parsers

#### 3. OCR + LLM Attachment Parser (`ocr_attachment_parser.py`)
- **Method**: Pytesseract OCR → GPT-4 for extraction
- **Pros**: Works on scanned PDFs, extracts bounding boxes
- **Cons**: OCR quality varies, slower processing
- **Best for**: Scanned documents, need bounding box coordinates

#### 4. Layout-Aware LLM Parser (`layout_attachment_parser.py`)
- **Method**: GPT-4-Vision for direct image/PDF analysis
- **Pros**: Understands visual layout, tables, charts
- **Cons**: Requires vision model access, highest API cost
- **Best for**: Complex structured documents (pitch decks, CIMs)

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

## Troubleshooting

### Import Errors

If you see import errors, ensure you're using `uv run`:

```bash
uv run python scripts/run_evaluation.py
uv run streamlit run streamlit_app.py
```

### spaCy Model Not Found

Download the required model using `uv pip`:

```bash
uv pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl
```

**Why not `python -m spacy download`?** UV creates virtual environments without `pip` by default, so we use `uv pip install` directly.

### OpenAI API Errors

Check that your API key is set:

```bash
echo $OPENAI_API_KEY
# or check .env file
```

### Tesseract Not Found (for OCR)

Install Tesseract:

```bash
# macOS
brew install tesseract

# Ubuntu/Debian
sudo apt-get install tesseract-ocr

# Set path in .env
TESSERACT_CMD=/opt/homebrew/bin/tesseract
```

## Next Steps

1. **Verify Ground Truth**: Review and correct `data/ground_truth_labels.csv`
2. **Run Evaluation**: Execute `scripts/run_evaluation.py` to test accuracy
3. **Explore Dashboard**: Launch Streamlit app to visualize results
4. **Iterate**: Improve prompts, add more test cases, tune extraction logic
5. **Production**: Deploy chosen approach for processing new emails

## Contact

Krystal Growth Partners

