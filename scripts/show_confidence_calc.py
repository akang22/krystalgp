"""Show detailed confidence-weighted calculation breakdown."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

print("="*100)
print("🧮 Confidence-Weighted EBITDA Calculation")
print("="*100)

print("\n📊 Individual Parser Results:")
print("-"*100)

results = [
    ("NER Body", 4.5, "body", 0.7),
    ("LLM Body", 4.5, "body", 1.0),
    ("Layout Vision", 3.6, "attachment", 0.9),
]

print(f"{'Parser':<20} {'EBITDA':<10} {'Source':<15} {'Base Weight':<12}")
print("-"*100)

for name, ebitda, source, base_weight in results:
    print(f"{name:<20} ${ebitda}M{'':<6} {source:<15} {base_weight}")

print("\n🔢 Confidence Calculation:")
print("-"*100)

# Parser weights
parser_weights = {
    'NER Body': 0.7,
    'LLM Body': 1.0,
    'Layout Vision': 0.9,
}

# Source weights
source_weights = {
    'body': 1.0,
    'attachment': 1.2,  # Attachments are more detailed
}

# Has raw text bonus
raw_text_bonus = 1.1

print(f"\n{'Parser':<20} {'EBITDA':<10} {'Calculation':<50} {'Weight':<10}")
print("-"*100)

total_weighted = 0
total_weight = 0

for name, ebitda, source, base_weight in results:
    # Calculate final weight
    parser_weight = parser_weights[name]
    source_weight = source_weights[source]
    has_raw = True  # All have raw text in this example
    
    final_weight = parser_weight * source_weight * (raw_text_bonus if has_raw else 1.0)
    
    weighted_value = ebitda * final_weight
    
    calc = f"{parser_weight} × {source_weight} × {raw_text_bonus if has_raw else 1.0}"
    
    print(f"{name:<20} ${ebitda}M{'':<6} {calc:<50} {final_weight:.3f}")
    
    total_weighted += weighted_value
    total_weight += final_weight

print("-"*100)

final_ebitda = total_weighted / total_weight

print(f"\n{'Total Weighted Sum:':<70} {total_weighted:.3f}")
print(f"{'Total Weight:':<70} {total_weight:.3f}")
print(f"{'Final EBITDA (weighted average):':<70} ${final_ebitda:.2f}M")

print("\n" + "="*100)
print("📈 Formula Breakdown:")
print("="*100)

print(f"""
Weighted Average = (Sum of EBITDA × Weight) / (Sum of Weights)

                 = ({results[0][1]} × {parser_weights['NER Body']} × {source_weights['body']} × {raw_text_bonus} + 
                    {results[1][1]} × {parser_weights['LLM Body']} × {source_weights['body']} × {raw_text_bonus} +
                    {results[2][1]} × {parser_weights['Layout Vision']} × {source_weights['attachment']} × {raw_text_bonus})
                   ÷
                   ({parser_weights['NER Body']} × {source_weights['body']} × {raw_text_bonus} + 
                    {parser_weights['LLM Body']} × {source_weights['body']} × {raw_text_bonus} +
                    {parser_weights['Layout Vision']} × {source_weights['attachment']} × {raw_text_bonus})

                 = {total_weighted:.3f} ÷ {total_weight:.3f}
                 
                 = ${final_ebitda:.2f}M
""")

print("="*100)
print("💡 Key Insights:")
print("="*100)
print("""
1. LLM Body gets highest base weight (1.0) - most reliable parser
2. Layout Vision gets 0.9 weight + 1.2× attachment bonus = strong influence
3. NER Body gets lowest weight (0.7) - fast but less accurate
4. All parsers get 1.1× bonus for having raw EBITDA text
5. Result ($4.19M) is closer to $4.5M because:
   - Two parsers agree on $4.5M (NER + LLM)
   - LLM has highest individual weight
   - But Layout Vision's attachment bonus pulls it slightly down
""")

print("\n" + "="*100)
print("🎯 Why This Is Better Than Simple Average:")
print("="*100)
print(f"""
Simple Average:     (4.5 + 4.5 + 3.6) / 3 = ${(4.5 + 4.5 + 3.6)/3:.2f}M
Confidence-Weighted:                        ${final_ebitda:.2f}M

The confidence-weighted result gives MORE weight to reliable parsers (LLM)
and considers that attachments often have more detailed/accurate data.
""")

print("="*100)

