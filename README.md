

# Email Parser for Investment Opportunities

A robust email parsing system for extracting investment opportunity data from `.msg` files using multiple approaches: LLM-based (GPT-4), NER/regex-based (spaCy), OCR-based (Tesseract), and layout-aware (GPT-4o Vision).

## Features

- **Multiple Parsing Approaches:**
  - LLM Body Parser (GPT-4)
  - NER Body Parser (spaCy + regex)
  - OCR + LLM Attachment Parser (Tesseract + GPT-4)
  - OCR + NER Attachment Parser (Tesseract + spaCy)
  - Layout-aware Vision Parser (GPT-4o Vision)
  - Ensemble Parser (combines all approaches)

- **Structured Data Extraction:**
  - EBITDA (with multiple options and confidence scores)
  - Company name
  - Headquarters location (with BC focus)
  - Industry sector
  - Source domain and recipient

- **Interactive Streamlit Dashboard:**
  - Upload and analyze `.msg` files
  - View extraction results from all parsers
  - Compare parser outputs side-by-side
  - Direct attachment viewing (PDF, DOCX, images)

## Setup

### Prerequisites

- Python 3.10-3.12 (required for torch on Intel Macs)
- [UV](https://github.com/astral-sh/uv) - Fast Python package installer
- Tesseract OCR (for OCR-based parsers)

### Installation

1. **Clone the repository:**

```bash
git clone <repository-url>
cd krystalgp
```

2. **Install dependencies with UV:**

```bash
# Install UV if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install project dependencies (includes spaCy model)
uv sync
```

3. **Install Tesseract (for OCR parsers):**

```bash
# macOS
brew install tesseract

# Ubuntu/Debian
sudo apt-get install tesseract-ocr

# Windows - download from https://github.com/UB-Mannheim/tesseract/wiki
```

4. **Configure API keys:**

**For CLI usage** (scripts), create `.env`:

```bash
cp .env.example .env
# Edit .env and add your OpenAI API key
```

**For Streamlit**, create `.streamlit/secrets.toml`:

```bash
mkdir -p .streamlit
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit .streamlit/secrets.toml and add your API keys
```

**Note:** 
- `OPENAI_API_KEY` is optional - only needed for LLM-based parsers
- NER and OCR+NER parsers work without any API keys
- Streamlit uses `secrets.toml` for security best practices
- CLI scripts use `.env` for local development

## Usage

### Run Streamlit Dashboard

```bash
uv run streamlit run streamlit_app.py
```

The dashboard allows you to:
- Upload `.msg` files directly
- Analyze emails with all parsers
- View detailed extraction results with confidence scores
- Preview attachments inline

### Run Individual Parsers

Test all parsers on a single email:

```bash
uv run python scripts/test_all_parsers.py
```

Test all emails in the dataset:

```bash
uv run python scripts/test_all_emails.py
```

Demo specific parsers:

```bash
uv run python scripts/demo_parsers.py
```

### Run Tests

```bash
uv run pytest
```

## Project Structure

```
krystalgp/
├── src/email_parser/
│   ├── base.py                          # Base classes and Pydantic models
│   ├── utils.py                         # Utility functions (EBITDA extraction, etc.)
│   ├── llm_body_parser.py              # LLM-based body parser (GPT-4)
│   ├── ner_body_parser.py              # NER + regex body parser
│   ├── ocr_attachment_parser.py        # OCR + LLM attachment parser
│   ├── ocr_ner_parser.py               # OCR + NER attachment parser
│   ├── layout_attachment_parser.py     # Layout-aware vision parser
│   └── ensemble_parser.py              # Combines all parsers
├── streamlit_app.py                     # Main Streamlit app
├── streamlit_pages/
│   └── email_analyzer.py               # Email analyzer page
├── scripts/
│   ├── test_all_parsers.py             # Test all parsers on one email
│   ├── test_all_emails.py              # Test on multiple emails
│   └── demo_parsers.py                 # Demo script
├── sample_emails/                       # Sample .msg files
├── tests/                               # Pytest tests
├── .env.example                         # Environment variable template (CLI)
├── .streamlit/secrets.toml.example     # Streamlit secrets template
└── README.md                            # This file
```

## Parser Details

### LLM Body Parser
- Uses OpenAI GPT-4
- Analyzes email body text
- Extracts multiple options with confidence scores
- BC location focus and temporal EBITDA context

### NER Body Parser
- Uses spaCy NER + custom regex
- Fast, offline parsing
- No API costs
- Good for structured emails

### OCR + LLM Parser
- Extracts text from PDFs/images using Tesseract
- Uses GPT-4 for structured extraction
- Handles scanned documents
- Table-aware extraction

### OCR + NER Parser
- OCR text extraction + NER/regex
- Completely offline
- No API costs
- Good baseline for attachments

### Layout Vision Parser
- Uses GPT-4o Vision
- Analyzes document layout directly
- Best for complex visual documents
- Handles tables, charts, and mixed layouts

### Ensemble Parser
- Combines all parser outputs
- Intelligent tie-breaking strategies:
  1. Fuzzy Consensus (values within ±$0.5M)
  2. Majority Vote
  3. Confidence Selection
  4. Source Prioritization (attachment > body)
  5. Historical Validation
- Produces "Final Results"

## Troubleshooting

### Import Error: `No module named 'email_parser'`

Make sure you're running scripts with `uv run`:

```bash
uv run python scripts/test_all_parsers.py
```

### spaCy Model Not Found

The spaCy model should be installed automatically with `uv sync`. If you still get this error, try:

```bash
# Reinstall dependencies
uv sync --reinstall

# Or install the model manually
uv pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
```

### OpenAI API Errors

The `OPENAI_API_KEY` is **optional**. If not set:
- LLM-based parsers will be unavailable
- NER and OCR+NER parsers will still work

For Streamlit, add your key to `.streamlit/secrets.toml`:

```toml
OPENAI_API_KEY = "sk-your-key-here"
```

For CLI, add to `.env`:

```bash
OPENAI_API_KEY=sk-your-key-here
```

### Tesseract Not Found

Install Tesseract OCR:

```bash
# macOS
brew install tesseract

# Check installation
which tesseract
```

The code auto-detects Tesseract location. If needed, set manually in `.streamlit/secrets.toml`:

```toml
TESSERACT_CMD = "/usr/local/bin/tesseract"
```

## Recent Improvements

### BC Focus & Temporal Context (Nov 2025)
All LLM-based parsers now include:
- **BC Location Prioritization**: Higher confidence for British Columbia cities (Vancouver, Victoria, Kelowna, etc.)
- **Temporal EBITDA Context**: Uses email date to prioritize TTM/LTM and current year EBITDA over historical data
- **Multiple Options**: Returns all possible values with confidence scores for tie-breaking

See `PROMPT_IMPROVEMENTS.md` for details.

### Ensemble Tie-Breaking
The ensemble parser uses intelligent selection strategies (not averaging) to resolve conflicts between parsers.

See `docs/TIE_BREAKING_STRATEGIES.md` for the full logic.

## License

MIT License

## Contributing

Contributions welcome! Please follow the coding standards in `.cursorrules`.
