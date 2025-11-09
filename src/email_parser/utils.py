"""Utility functions for email parsing.

This module provides helper functions for text processing, pattern matching,
and data normalization.
"""

import re
from typing import List, Optional, Tuple

# Common EBITDA patterns (expanded for OCR and various formats)
EBITDA_PATTERNS = [
    # "C$X.XM" or "$X.XM" with EBITDA nearby
    r'C?\$\s*(\d+\.?\d*)\s*M[a-z]*\s*(?:Adjusted\s+)?(?:Portfolio\s+)?EBITDA',
    # "EBITDA C$X.XM" or "EBITDA $X.XM"
    r'(?:Adjusted\s+)?(?:Portfolio\s+)?EBITDA[:\s]+C?\$\s*(\d+\.?\d*)\s*M',
    # "$X.XM EBITDA" or "$XM EBITDA"
    r'C?\$\s*(\d+\.?\d*)\s*M\s+EBITDA',
    # "EBITDA: $X.XM" or "EBITDA $XM"
    r'EBITDA[:\s]+C?\$\s*(\d+\.?\d*)\s*M',
    # "LTM EBITDA $X.XM"
    r'LTM\s+EBITDA[:\s]+C?\$\s*(\d+\.?\d*)\s*M',
    # "EBITDA of $X.XM"
    r'EBITDA\s+of\s+C?\$\s*(\d+\.?\d*)\s*M',
    # "$Xmm EBITDA" or "$X million EBITDA"
    r'C?\$\s*(\d+\.?\d*)\s*(?:mm|million)\s+EBITDA',
    # "($Xm)" format
    r'\(C?\$(\d+\.?\d*)[Mm]\)',
    # Negative EBITDA
    r'-C?\$\s*(\d+\.?\d*)\s*M\s+EBITDA',
    # Just "X.X M" or "X.X million" near EBITDA (for OCR artifacts)
    r'EBITDA[:\s]+C?\$?\s*(\d+\.?\d*)\s*(?:M|million)',
]


def extract_ebitda(text: str, allow_context_search: bool = True) -> Optional[Tuple[float, str]]:
    """Extract EBITDA value from text.
    
    Searches for common EBITDA patterns and returns the first match.
    
    Args:
        text: Text to search
        allow_context_search: If True, search for C$X.XM in tables near "EBITDA" headers
        
    Returns:
        Tuple of (ebitda_value, raw_text) or None if not found
        
    Examples:
        >>> extract_ebitda("The company has $5.2M EBITDA")
        (5.2, "$5.2M EBITDA")
        >>> extract_ebitda("LTM EBITDA: $10M")
        (10.0, "LTM EBITDA: $10M")
    """
    if not text:
        return None
    
    for pattern in EBITDA_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                value = float(match.group(1))
                # Check for negative EBITDA
                if '-' in match.group(0):
                    value = -value
                return (value, match.group(0))
            except (ValueError, IndexError):
                continue
    
    # If no direct match and context search enabled, look for table formats
    if allow_context_search and 'EBITDA' in text.upper():
        # Look for C$X.XM or $X.XM format in proximity to EBITDA
        # Common in tables where header says "EBITDA" and values are below
        lines = text.split('\n')
        
        # Strategy 1: Look for "Adjusted" EBITDA specifically (most reliable)
        for i, line in enumerate(lines):
            if 'ADJUSTED' in line.upper() and 'EBITDA' in line.upper():
                # Check next 3 lines for dollar amounts
                for j in range(i+1, min(i+4, len(lines))):
                    next_line = lines[j]
                    money_match = re.search(r'C?\$\s*(\d+\.?\d*)\s*M\b', next_line, re.IGNORECASE)
                    if money_match:
                        try:
                            value = float(money_match.group(1))
                            if 0.1 <= value <= 100:
                                return (value, f"C${value}M [Adjusted EBITDA from table]")
                        except ValueError:
                            continue
        
        # Strategy 2: Find all C$X.XM values near EBITDA and pick largest
        # (adjusted/portfolio EBITDA is usually the main metric)
        found_values = []
        for i, line in enumerate(lines):
            if 'EBITDA' in line.upper():
                # Check next 5 lines
                for j in range(i+1, min(i+6, len(lines))):
                    next_line = lines[j]
                    # Find all money values
                    money_matches = re.findall(r'C?\$\s*(\d+\.?\d*)\s*M\b', next_line, re.IGNORECASE)
                    for match_str in money_matches:
                        try:
                            value = float(match_str)
                            if 0.1 <= value <= 100:
                                found_values.append(value)
                        except ValueError:
                            continue
        
        # Return largest value (usually the total/consolidated EBITDA)
        if found_values:
            max_value = max(found_values)
            return (max_value, f"C${max_value}M [from table near EBITDA]")
    
    return None


def extract_location(text: str, max_words: int = 3) -> Optional[str]:
    """Extract location from text using common patterns.
    
    Looks for patterns like "based in X", "located in X", "X-based", etc.
    
    Args:
        text: Text to search
        max_words: Maximum number of words in location
        
    Returns:
        Location string or None if not found
        
    Examples:
        >>> extract_location("Company is based in Vancouver, BC")
        "Vancouver, BC"
    """
    if not text:
        return None
    
    # Patterns for location extraction
    patterns = [
        r'based in ([A-Z][a-zA-Z\s,]+)',
        r'located in ([A-Z][a-zA-Z\s,]+)',
        r'headquartered in ([A-Z][a-zA-Z\s,]+)',
        r'HQ[:\s]+([A-Z][a-zA-Z\s,]+)',
        r'([A-Z][a-zA-Z\s]+)-based',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            location = match.group(1).strip()
            # Limit to max_words
            words = location.split()[:max_words]
            return ' '.join(words).rstrip(',.')
    
    return None


def normalize_text(text: str) -> str:
    """Normalize text by removing extra whitespace and special characters.
    
    Args:
        text: Text to normalize
        
    Returns:
        Normalized text
    """
    if not text:
        return ""
    
    # Replace multiple whitespaces with single space
    text = re.sub(r'\s+', ' ', text)
    
    # Remove excessive punctuation
    text = re.sub(r'\.{2,}', '.', text)
    
    return text.strip()


def extract_canadian_provinces(text: str) -> List[str]:
    """Extract Canadian province abbreviations from text.
    
    Args:
        text: Text to search
        
    Returns:
        List of province abbreviations found
    """
    provinces = ['AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'NT', 'NU', 'ON', 'PE', 'QC', 'SK', 'YT']
    found = []
    
    for province in provinces:
        # Look for province abbreviation with word boundaries
        if re.search(rf'\b{province}\b', text):
            found.append(province)
    
    return found


def identify_krystal_gp_member(recipients: List[str]) -> Optional[str]:
    """Identify which Krystal GP member received the email.
    
    Based on common team member initials from results.csv:
    MS, MA, AH, TMH, BL, KM, MJA
    
    Args:
        recipients: List of recipient email addresses
        
    Returns:
        Email address of Krystal GP member or None
    """
    if not recipients:
        return None
    
    # Krystal GP domain patterns
    krystal_domains = ['krystalgp.com', 'krystal.com']
    
    for recipient in recipients:
        recipient_lower = recipient.lower()
        for domain in krystal_domains:
            if domain in recipient_lower:
                return recipient
    
    # If no Krystal domain found, return first recipient
    return recipients[0] if recipients else None


def clean_company_name(name: str) -> str:
    """Clean and normalize company/project name.
    
    Removes common prefixes like "Project ", "Confidential: ", etc.
    
    Args:
        name: Company or project name
        
    Returns:
        Cleaned name
    """
    if not name:
        return ""
    
    # Remove common prefixes
    prefixes_to_remove = [
        'Project ',
        'Confidential: ',
        'Acquisition Opportunity - ',
        'Acquisition Opportunity: ',
        'Investment Opportunity - ',
        'Investment Opportunity: ',
        'FW: ',
        'RE: ',
        'Fwd: ',
    ]
    
    for prefix in prefixes_to_remove:
        if name.startswith(prefix):
            name = name[len(prefix):]
    
    return name.strip()


def fuzzy_match_ebitda(predicted: Optional[float], actual: Optional[float], 
                       tolerance: float = 0.5) -> bool:
    """Check if two EBITDA values match within tolerance.
    
    Args:
        predicted: Predicted EBITDA value
        actual: Actual EBITDA value
        tolerance: Tolerance in millions
        
    Returns:
        True if values match within tolerance
    """
    if predicted is None or actual is None:
        return False
    
    return abs(predicted - actual) <= tolerance


