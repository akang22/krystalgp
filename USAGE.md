# Email Parser - Quick Start Guide

## 🚀 Running the Streamlit Dashboard

```bash
# Option 1: Direct command
cd /Users/yanjunk/projects/krystalgp
uv run streamlit run streamlit_app.py

# Option 2: Helper script
./run_streamlit.sh
```

Then open your browser to: **http://localhost:8501**

---

## 📊 Dashboard Pages

### **Page 1: Email Analyzer** ⭐ NEW!

**Select any email and see:**
- 📧 Email metadata (sender, recipient, date, subject)
- 📎 Attachments list with sizes
- 📄 Email body content
- 🔍 Results from all 5 parsers side-by-side
- 🧮 **Confidence-weighted calculation breakdown**
  - Shows weights for each parser
  - Displays formula and final result
  - Compares simple average vs weighted
- 📋 Detailed results for each parser
- 💾 Export results as CSV

**Example Output:**
```
Parser               EBITDA      Company         HQ Location       Time
─────────────────────────────────────────────────────────────────────────
NER Body             $4.50M      Project Gravy   Bakowska         0.81s
LLM Body             $4.50M      Project Gravy   Vancouver, BC    4.16s
Layout Vision        $3.60M      Project Gravy   BC, Canada       5.39s
Ensemble (Weighted)  $4.19M      Project Gravy   Vancouver, BC   12.05s
```

### **Page 2: Parser Comparison**
- Accuracy metrics across all emails
- Performance benchmarks
- Bar charts comparing approaches

### **Page 3: Side-by-Side Viewer**
- Compare ground truth vs parser results
- Field-by-field comparison

### **Page 4: Batch Processing**
- Process multiple emails at once
- Download batch results

---

## 🧮 How Confidence Weighting Works

When parsers disagree (e.g., $4.5M vs $3.6M), the ensemble uses:

**Parser Base Weights:**
- LLM Body: **1.0** (most reliable)
- Layout Vision: **0.9** (very reliable)
- NER Body: **0.7** (baseline)
- OCR + LLM: **0.5** (less reliable)

**Source Multipliers:**
- Attachment: **1.2×** (more detailed documents)
- Body: **1.0×**
- Both: **1.1×**

**Bonuses:**
- Has raw EBITDA text: **1.1×**

**Final Formula:**
```
Final EBITDA = Σ(EBITDA × Weight) / Σ(Weight)

Example:
  NER:    $4.5M × (0.7 × 1.0 × 1.1) = 3.465
  LLM:    $4.5M × (1.0 × 1.0 × 1.1) = 4.950
  Vision: $3.6M × (0.9 × 1.2 × 1.1) = 4.277
  
  Total: 12.692 / 3.058 = $4.15M
```

---

## 🎯 Which Parser to Use?

| Use Case | Recommended Parser | Why |
|----------|-------------------|-----|
| **Production** | **Ensemble (Confidence)** | Best accuracy, handles conflicts |
| **Speed-critical** | NER Body | 0.8s, no API costs |
| **Best accuracy** | LLM Body | Best body text understanding |
| **PDF documents** | Layout Vision | GPT-4o vision model |
| **Offline/free** | NER Body | Works without API keys |

---

## 🧪 Testing Individual Parsers

```bash
# Test all parsers on one email
uv run python scripts/test_all_parsers.py

# Show confidence calculation
uv run python scripts/show_confidence_calc.py

# Demo with multiple emails
uv run python scripts/demo_parsers.py

# Full evaluation on all emails
uv run python scripts/run_evaluation.py
```

---

## 📈 Current Test Results

**Email:** FW Project Gravy - Franchise QSR Portfolio Acquisition Opportunity.msg

| Parser | EBITDA | Source | Accuracy |
|--------|--------|--------|----------|
| NER Body | $4.50M | Body text | ✅ Matches ground truth |
| LLM Body | $4.50M | Body text | ✅ Better location extraction |
| Layout Vision | $3.60M | PDF attachment | ⚠️ Different metric ("Portfolio EBITDA") |
| **Ensemble** | **$4.19M** | **Combined** | ⭐ Weighted average |

**Key Finding:** The email body mentions "$4.5M EBITDA" while the PDF teaser shows "C$3.6M Adjusted Portfolio EBITDA" - both are valid but refer to different metrics!

---

## 🔧 Troubleshooting

### Streamlit Import Error

If you see module import errors, make sure the path is correct:

```python
# This is already in streamlit_app.py
sys.path.insert(0, str(Path(__file__).parent / "src"))
```

### OCR Not Working

Install Tesseract:

```bash
brew install tesseract
```

### API Key Not Found

Check your `.env` file exists and has:

```bash
OPENAI_API_KEY=sk-your-actual-key-here
```

---

## 📦 Next Steps

1. **Review Ground Truth**: Edit `data/ground_truth_labels.csv` with correct values
2. **Run Full Evaluation**: `uv run python scripts/run_evaluation.py`
3. **Explore Dashboard**: Test different emails in Email Analyzer
4. **Tune Weights**: Adjust confidence weights based on your accuracy findings
5. **Deploy**: Choose best parser(s) for production use

