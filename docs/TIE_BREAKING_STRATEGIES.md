# 🎯 Tie-Breaking Strategies for Conflicting Parser Results

## The Problem

When different parsers extract different EBITDA values from the same email:
- NER Body: $4.50M (from email body)
- LLM Body: $4.50M (from email body)
- Layout Vision: $3.60M (from PDF attachment)

**Which value is correct?**

---

## ✅ Current Implementation: Selection-Based (NOT Averaging)

The ensemble parser **SELECTS** the best value using this priority:

### 1️⃣ **Fuzzy Consensus** (Primary) ⭐
**Strategy:** If multiple parsers return values within ±$0.5M, treat as "same" and select that value.

**Example:**
```
Parser Results: [$4.50M, $4.50M, $3.60M]
→ Cluster 1: [$4.5, $4.5] (2 parsers)
→ Cluster 2: [$3.6] (1 parser)
→ SELECT: $4.50M (majority cluster)
```

**Why it's good:** Handles minor rounding differences, respects majority agreement

---

### 2️⃣ **Majority Vote** (Exact Match)
**Strategy:** If >50% of parsers return the exact same value, select it.

**Example:**
```
Parser Results: [$5.0M, $5.0M, $5.0M, $8.0M]
→ $5.0M appears 3/4 times (75%)
→ SELECT: $5.0M
```

---

### 3️⃣ **Confidence Selection** (Highest Score)
**Strategy:** If values are different, select from parser with highest confidence score.

**Confidence Scoring:**
```python
score = parser_weight × source_weight × raw_text_bonus

Parser Weights:
- LLM:    1.0  (highest reliability)
- Vision: 0.9  (high reliability, layout-aware)
- NER:    0.7  (baseline)
- OCR:    0.5  (OCR quality varies)

Source Weights:
- Attachment: 1.2× (detailed documents)
- Body:       1.0× (email text)
- Both:       1.1×

Raw Text Bonus:
- Has raw EBITDA text: 1.1×
- No raw text:         1.0×
```

**Example:**
```
NER:    $4.5M → score = 0.7 × 1.0 × 1.1 = 0.77
LLM:    $4.5M → score = 1.0 × 1.0 × 1.1 = 1.10  ← HIGHEST
Vision: $3.6M → score = 0.9 × 1.2 × 1.1 = 1.19  ← HIGHEST!

→ SELECT: $3.6M (Vision has highest score due to attachment bonus)
```

---

### 4️⃣ **Source Prioritization**
**Strategy:** Prefer attachment-based over body-based (documents are more detailed).

**Example:**
```
LLM Body:      $4.5M (from email)
Layout Vision: $3.6M (from PDF)
→ SELECT: $3.6M (attachment source prioritized)
```

---

### 5️⃣ **Historical Validation**
**Strategy:** Compare against `results.csv`, select value closest to historical data.

**Example:**
```
Parser Results: [$4.5M, $3.6M]
Historical (results.csv): $4.5M
→ SELECT: $4.5M (matches historical)
```

---

## 🔄 Full Strategy Chain

The ensemble tries strategies in order:

```
1. Fuzzy Consensus → If values are close (±$0.5M), pick consensus
   ↓ (if multiple distinct values)
   
2. Majority Vote → If >50% agree exactly, pick that value
   ↓ (if no majority)
   
3. Confidence Selection → Pick value from highest-scored parser
   ↓ (if all failed)
   
4. Source Prioritization → Prefer attachment over body
   ↓ (if all failed)
   
5. Historical Validation → Compare with results.csv
   ↓ (if all failed)
   
6. First Available → Return first non-None value
```

---

## 📊 Real Example: Project Gravy

**Parser Results:**
- NER Body: $4.50M (body, score: 0.77)
- LLM Body: $4.50M (body, score: 1.10)
- Layout Vision: $3.60M (attachment, score: 1.19)

**Selection Process:**

✅ **Step 1: Fuzzy Consensus**
- Values: [$4.5, $4.5, $3.6]
- Cluster 1: [$4.5, $4.5] - 2 parsers (MAJORITY)
- Cluster 2: [$3.6] - 1 parser
- **→ SELECT: $4.50M** ✓

*Strategy stopped here - fuzzy consensus found majority cluster*

---

## 🚫 What We DON'T Do

❌ **NO Averaging:** We never compute `(4.5 + 4.5 + 3.6) / 3 = 4.2`
   - Meaningless to average different metrics
   - $4.5M "adjusted EBITDA" ≠ $3.6M "portfolio EBITDA"

❌ **NO Blending:** Values are selected whole, not interpolated

✅ **YES Selection:** Pick ONE value based on evidence and confidence

---

## 💡 When Should You Use Each Strategy?

| Situation | Best Strategy | Why |
|-----------|---------------|-----|
| Parsers mostly agree | Fuzzy Consensus | Handles rounding differences |
| One parser is known reliable | Confidence Selection | Trust the best source |
| Attachments are more detailed | Source Prioritization | PDFs have more data |
| You have historical data | Historical Validation | Ground truth reference |
| High-stakes decision | Human-in-the-Loop | Manual review |

---

## 🔧 Customizing Weights

Edit `src/email_parser/ensemble_parser.py`:

```python
# Adjust parser reliability weights
parser_weights = {
    'LLM': 1.0,    # ← Increase if LLM is very accurate
    'Vision': 0.9,  # ← Increase for better PDFs
    'NER': 0.7,     # ← Your baseline
    'OCR': 0.5,     # ← Decrease if OCR quality is poor
}

# Adjust source importance
source_weights = {
    'attachment': 1.2,  # ← Increase to trust PDFs more
    'body': 1.0,        # ← Email text baseline
}
```

---

## 📈 Validation Through Testing

Run full evaluation to see which strategy performs best:

```bash
uv run python scripts/run_evaluation.py
```

Then compare accuracy across your 99 emails to calibrate weights!

---

**Bottom line:** We **select** the most trustworthy value, we **don't blend** meaningless averages. ✅

