"""Utility functions for email parsing.

This module provides helper functions for text processing, pattern matching,
and data normalization.
"""

import re
from typing import List, Optional, Tuple

# Common EBITDA patterns
EBITDA_PATTERNS = [
    # "$X.XM EBITDA" or "$XM EBITDA"
    r'\$\s*(\d+\.?\d*)\s*M\s+EBITDA',
    # "EBITDA: $X.XM" or "EBITDA $XM"
    r'EBITDA[:\s]+\$\s*(\d+\.?\d*)\s*M',
    # "LTM EBITDA $X.XM"
    r'LTM\s+EBITDA[:\s]+\$\s*(\d+\.?\d*)\s*M',
    # "EBITDA of $X.XM"
    r'EBITDA\s+of\s+\$\s*(\d+\.?\d*)\s*M',
    # "$Xmm EBITDA" or "$X million EBITDA"
    r'\$\s*(\d+\.?\d*)\s*(?:mm|million)\s+EBITDA',
    # "($Xm)" format
    r'\(\$(\d+\.?\d*)[Mm]\)',
    # Negative EBITDA
    r'-\$\s*(\d+\.?\d*)\s*M\s+EBITDA',
]


def extract_ebitda(text: str) -> Optional[Tuple[float, str]]:
    """Extract EBITDA value from text.
    
    Searches for common EBITDA patterns and returns the first match.
    
    Args:
        text: Text to search
        
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

