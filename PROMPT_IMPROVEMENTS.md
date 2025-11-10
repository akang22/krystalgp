# LLM Prompt Improvements

## Changes Made

### 1. BC (British Columbia) Location Focus

**Added:**
- Explicit context that firm is focused on BC, Canada
- List of BC cities to prioritize: Vancouver, Victoria, Kelowna, Surrey, Burnaby, Richmond, Abbotsford
- Higher confidence scores for BC locations:
  - BC explicit: 0.95
  - BC implied: 0.85
  - Non-BC explicit: 0.7
  - Non-BC general: 0.5

**Impact:**
- Vancouver, BC now gets 95% confidence vs 90% before
- British Columbia gets 95% vs 60% before
- Better prioritization of BC-based companies

### 2. Temporal EBITDA Context

**Added:**
- Email received date in prompt context
- Instruction to prioritize TTM (Trailing Twelve Months) or LTM (Last Twelve Months)
- Warning to AVOID historical data from previous years
- Guidance to select MOST RECENT when multiple years shown

**Example:**
```
Email from 2024:
- PRIORITIZE: "TTM EBITDA", "LTM EBITDA", "2024 EBITDA"
- AVOID: "2023 EBITDA" unless marked as current
```

**Confidence scoring:**
- Explicit LTM/TTM with clear $: 0.95
- Current year: 0.9
- Implied/estimated: 0.6-0.8
- Old data: 0.3

**Impact:**
- Reduces risk of extracting outdated EBITDA values
- Prioritizes most recent financial data
- Handles multi-year tables correctly

### 3. Additional Improvements

**EBITDA:**
- Look for "Adjusted EBITDA", "Pro Forma EBITDA", "Portfolio EBITDA"
- Better handling of different formats: $5.2M, $3,600K, C$10M

**Company:**
- Check subject line first for project names
- Extract official names from body

**Sector:**
- More specific instructions: "Quick Service Restaurants" not just "Food"

## Test Results

**Email:** "FW Project Gravy - Franchise QSR Portfolio Acquisition Opportunity.msg"

### Before:
- Location: British Columbia (60% confidence)
- EBITDA: $4.5M (no temporal context)

### After:
- Location: Vancouver, BC (95% confidence)
- Location: British Columbia (95% confidence)  
- Location: Ontario (70% confidence)
- EBITDA: $4.5M (with 2024 context)

## Files Modified

1. `src/email_parser/llm_body_parser.py` - Main body parser
2. `src/email_parser/ocr_attachment_parser.py` - OCR + LLM parser
3. `src/email_parser/layout_attachment_parser.py` - Layout Vision parser

All LLM-based parsers now use:
- Email date for temporal context
- BC location prioritization
- Enhanced EBITDA extraction logic
- Full email body (no truncation)

