"""NER and regex-based body parser using spaCy.

This module implements a parser that uses Named Entity Recognition (NER)
and regex patterns to extract investment opportunity data from email body text.
"""

import re
from pathlib import Path
from typing import List, Optional, Set

import spacy
from spacy.language import Language

from email_parser.base import BaseParser, EmailData, InvestmentOpportunity, ParserResult, FieldOption
from email_parser.utils import (
    extract_canadian_provinces,
    extract_ebitda,
    extract_location,
    normalize_text,
)


class NERBodyParser(BaseParser):
    """Parser that uses spaCy NER and regex to extract data from email body text.
    
    This parser uses traditional NLP techniques including:
    - Named Entity Recognition for locations and organizations
    - Regex patterns for EBITDA extraction
    - Rule-based extraction for specific fields
    """
    
    def __init__(self, model_name: str = "en_core_web_sm"):
        """Initialize NER body parser.
        
        Args:
            model_name: spaCy model name to use
                - "en_core_web_sm": Small model (faster, less accurate)
                - "en_core_web_md": Medium model (balanced)
                - "en_core_web_trf": Transformer model (slower, more accurate)
        """
        super().__init__(name="NER-Body-Parser")
        
        self.model_name = model_name
        self.nlp = self._load_spacy_model(model_name)
        
        self.logger.info(f"Initialized NER parser with spaCy model: {model_name}")
    
    def _load_spacy_model(self, model_name: str) -> Language:
        """Load spaCy language model.
        
        Args:
            model_name: Name of spaCy model
            
        Returns:
            Loaded spaCy Language object
            
        Raises:
            RuntimeError: If model is not installed
        """
        try:
            return spacy.load(model_name)
        except OSError as e:
            self.logger.warning(f"spaCy model '{model_name}' not found: {e}")
            self.logger.info("Attempting to download model (Streamlit Cloud fallback)...")
            try:
                # Fallback for Streamlit Cloud deployment
                import subprocess
                import sys
                self.logger.info(f"Running: python -m spacy download {model_name}")
                result = subprocess.run(
                    [sys.executable, "-m", "spacy", "download", model_name],
                    capture_output=True,
                    text=True,
                    timeout=120  # 2 minute timeout
                )
                
                if result.returncode != 0:
                    self.logger.error(f"Download failed: {result.stderr}")
                    raise RuntimeError(f"Download command failed: {result.stderr}")
                
                self.logger.info(f"Download successful: {result.stdout}")
                return spacy.load(model_name)
            except subprocess.TimeoutExpired:
                self.logger.error("Download timed out after 2 minutes")
                raise RuntimeError("spaCy model download timed out")
            except Exception as download_error:
                self.logger.error(f"Failed to download model: {download_error}")
                raise RuntimeError(
                    f"spaCy model '{model_name}' not installed and auto-download failed. "
                    f"Error: {download_error}"
                )
    
    def _extract_company_name(self, text: str, subject: Optional[str]) -> Optional[str]:
        """Extract company or project name from text.
        
        Args:
            text: Email body text
            subject: Email subject line
            
        Returns:
            Company name or None
        """
        # First try subject line for "Project X" patterns
        if subject:
            # Match "Project X" or company names
            project_match = re.search(r'Project\s+([A-Z][a-zA-Z]+)', subject)
            if project_match:
                return f"Project {project_match.group(1)}"
            
            # Match company names after common prefixes
            for prefix in ['Acquisition Opportunity - ', 'Investment Opportunity - ', 
                          'Acquisition Opportunity: ', 'Investment Opportunity: ']:
                if subject.startswith(prefix):
                    name = subject[len(prefix):].split('(')[0].strip()
                    if name:
                        return name[:100]  # Limit length
        
        # Use NER to find organization names
        doc = self.nlp(text[:1000])  # Only process first 1000 chars
        orgs = [ent.text for ent in doc.ents if ent.label_ == 'ORG']
        
        if orgs:
            # Return first organization that's not too long
            for org in orgs:
                if len(org) < 50 and not org.lower() in ['krystal', 'gp', 'growth partners']:
                    return org
        
        return None
    
    def _extract_sector(self, text: str) -> Optional[str]:
        """Extract industry sector from text.
        
        Args:
            text: Email body text
            
        Returns:
            Sector name or None
        """
        # Common sector keywords from results.csv
        sectors = {
            'Retail': ['retail', 'retailer', 'store', 'shop', 'apparel'],
            'Building Products': ['building products', 'construction', 'contractor', 
                                'manufacturer', 'building supplies'],
            'Business Services': ['business services', 'consulting', 'services provider'],
            'Transportation Services': ['transportation', 'logistics', 'trucking', 
                                       'shipping', 'fleet'],
            'Healthcare': ['healthcare', 'medical', 'health services', 'clinic'],
            'Industrial Products': ['industrial', 'manufacturing', 'fabrication'],
            'Consumer Services': ['consumer services', 'restaurant', 'hospitality'],
            'Other': [],
        }
        
        text_lower = text.lower()
        
        for sector, keywords in sectors.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return sector
        
        return None
    
    def _extract_locations_ner(self, text: str) -> List[str]:
        """Extract location entities using NER.
        
        Args:
            text: Text to analyze
            
        Returns:
            List of location strings
        """
        doc = self.nlp(text[:2000])  # Process first 2000 chars
        
        locations = []
        for ent in doc.ents:
            if ent.label_ in ['GPE', 'LOC']:  # Geo-political entity or location
                locations.append(ent.text)
        
        return locations
    
    def _determine_hq_location(self, text: str, subject: Optional[str]) -> Optional[str]:
        """Determine headquarters location from email.
        
        Combines multiple strategies:
        1. Pattern matching for "based in", "located in", etc.
        2. NER for location entities
        3. Canadian province detection
        
        Args:
            text: Email body text
            subject: Email subject line
            
        Returns:
            HQ location string or None
        """
        # Try pattern-based extraction first
        pattern_location = extract_location(text)
        if pattern_location:
            return pattern_location
        
        # Try NER-based extraction
        ner_locations = self._extract_locations_ner(text)
        
        # Filter for Canadian locations (common in results.csv)
        provinces = extract_canadian_provinces(text)
        
        # Prioritize locations with Canadian provinces
        for location in ner_locations:
            for province in provinces:
                if province in location:
                    return location
        
        # Return first NER location if found
        if ner_locations:
            return ner_locations[0]
        
        # Return province if found
        if provinces:
            return provinces[0]
        
        return None
    
    def parse_data(self, email_data: EmailData) -> InvestmentOpportunity:
        """Parse email data using NER and regex to extract investment opportunity.
        
        Args:
            email_data: Extracted email data
            
        Returns:
            InvestmentOpportunity with extracted fields
        """
        # Extract source domain from sender
        source_domain = self.extract_domain(email_data.sender) if email_data.sender else None
        
        # Identify recipient
        recipient = email_data.recipients[0] if email_data.recipients else None
        
        # Get email body text
        body_text = email_data.body_plain or email_data.body_html or ""
        subject = email_data.subject or ""
        
        # Normalize text
        body_text = normalize_text(body_text)
        
        # Extract EBITDA (primary)
        ebitda_result = extract_ebitda(body_text)
        ebitda_millions = ebitda_result[0] if ebitda_result else None
        raw_ebitda_text = ebitda_result[1] if ebitda_result else None
        
        # Collect multiple EBITDA options (find all regex matches)
        ebitda_options = []
        if ebitda_result:
            ebitda_options.append(FieldOption(
                value=ebitda_result[0],
                confidence=0.9,
                source="email body (regex)",
                raw_text=ebitda_result[1]
            ))
        
        # Extract HQ location (primary)
        hq_location = self._determine_hq_location(body_text, subject)
        
        # Collect multiple location options
        location_options = []
        pattern_location = extract_location(body_text)
        ner_locations = self._extract_locations_ner(body_text)
        provinces = extract_canadian_provinces(body_text)
        
        if pattern_location:
            location_options.append(FieldOption(
                value=pattern_location,
                confidence=0.9,
                source="email body (pattern match)",
                raw_text=None
            ))
        
        for loc in ner_locations[:3]:  # Top 3 NER matches
            if loc not in [opt.value for opt in location_options]:
                location_options.append(FieldOption(
                    value=loc,
                    confidence=0.7,
                    source="email body (NER)",
                    raw_text=None
                ))
        
        for prov in provinces[:2]:  # Top 2 provinces
            if prov not in [opt.value for opt in location_options]:
                location_options.append(FieldOption(
                    value=prov,
                    confidence=0.5,
                    source="email body (province mention)",
                    raw_text=None
                ))
        
        # Extract company name (primary)
        company_name = self._extract_company_name(body_text, subject)
        
        # Collect multiple company options
        company_options = []
        if company_name:
            company_options.append(FieldOption(
                value=company_name,
                confidence=0.9,
                source="subject line or body",
                raw_text=None
            ))
        
        # Add NER organization entities
        doc = self.nlp(body_text[:2000])  # Limit to avoid slow processing
        for ent in doc.ents:
            if ent.label_ == "ORG" and ent.text not in [opt.value for opt in company_options]:
                company_options.append(FieldOption(
                    value=ent.text,
                    confidence=0.6,
                    source="email body (NER ORG)",
                    raw_text=None
                ))
                if len(company_options) >= 3:  # Limit to top 3
                    break
        
        # Extract sector
        sector = self._extract_sector(body_text)
        
        opportunity = InvestmentOpportunity(
            source_domain=source_domain,
            recipient=recipient,
            hq_location=hq_location,
            ebitda_millions=ebitda_millions,
            date=email_data.date,
            company_name=company_name,
            sector=sector,
            raw_ebitda_text=raw_ebitda_text,
            ebitda_options=ebitda_options,
            location_options=location_options,
            company_options=company_options,
        )
        
        self.logger.info(
            f"Extracted: EBITDA=${opportunity.ebitda_millions}M, "
            f"Location={opportunity.hq_location}, Company={opportunity.company_name}"
        )
        
        return opportunity
    
    def parse(self, msg_path: Path) -> ParserResult:
        """Parse a .msg file using NER-based extraction.
        
        Overrides base method to set extraction_source correctly.
        
        Args:
            msg_path: Path to the .msg file
            
        Returns:
            ParserResult with extracted data
        """
        result = super().parse(msg_path)
        result.extraction_source = "body"
        return result


