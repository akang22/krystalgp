"""LLM-based body parser using OpenAI GPT-4.

This module implements a parser that uses OpenAI's GPT models to extract
structured investment opportunity data from email body text.
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

from email_parser.base import BaseParser, EmailData, InvestmentOpportunity, ParserResult, FieldOption

# Load environment variables from .env file
load_dotenv()


class LLMBodyParser(BaseParser):
    """Parser that uses OpenAI GPT-4 to extract data from email body text.
    
    This parser sends the email body to GPT-4 with a structured prompt
    and JSON schema to extract investment opportunity fields.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4-turbo-preview",
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ):
        """Initialize LLM body parser.
        
        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: OpenAI model to use
            temperature: Temperature for generation (lower = more deterministic)
            max_tokens: Maximum tokens in response
        """
        super().__init__(name="LLM-Body-Parser")
        
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY env var or pass api_key.")
        
        self.client = OpenAI(api_key=self.api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        self.logger.info(f"Initialized LLM parser with model: {model}")
    
    def _build_extraction_prompt(self, email_data: EmailData) -> str:
        """Build prompt for GPT-4 to extract investment opportunity data.
        
        Args:
            email_data: Email data to process
            
        Returns:
            Formatted prompt string
        """
        # Use plain text body, fall back to HTML if needed
        body_text = email_data.body_plain or email_data.body_html or ""
        
        # Get email year for context
        email_year = email_data.date.year if email_data.date else datetime.now().year
        
        prompt = f"""You are an expert at extracting structured information from investment opportunity emails for a private equity firm focused on British Columbia (BC), Canada.

**CONTEXT:**
- This email was received in {email_year}
- The firm is particularly interested in BC-based companies or those with operations in British Columbia
- We need the MOST RECENT financial data (TTM, LTM, or {email_year} EBITDA)

Extract the following fields from the email below. For each field, provide ALL possible values you find with confidence scores.

Return ONLY a valid JSON object with these exact fields:

{{
  "ebitda_options": [
    {{"value": 5.2, "confidence": 0.95, "source": "email body", "raw_text": "LTM EBITDA of $5.2M"}},
    {{"value": 4.5, "confidence": 0.7, "source": "subject line", "raw_text": "~$4.5M EBITDA"}}
  ],
  "location_options": [
    {{"value": "Vancouver, BC", "confidence": 0.95, "source": "email body", "raw_text": "headquartered in Vancouver"}},
    {{"value": "British Columbia", "confidence": 0.85, "source": "general mention", "raw_text": "BC operations"}},
    {{"value": "Toronto, ON", "confidence": 0.6, "source": "secondary location", "raw_text": "office in Toronto"}}
  ],
  "company_options": [
    {{"value": "Project Gravy", "confidence": 0.95, "source": "subject line", "raw_text": "Project Gravy -"}}
  ],
  "sector_options": [
    {{"value": "Quick Service Restaurants", "confidence": 0.95, "source": "email body", "raw_text": "QSR portfolio"}},
    {{"value": "Food & Beverage", "confidence": 0.7, "source": "general category", "raw_text": "restaurant operations"}}
  ]
}}

**CRITICAL INSTRUCTIONS:**

FOR EBITDA:
- PRIORITIZE: TTM (Trailing Twelve Months), LTM (Last Twelve Months), or {email_year} EBITDA
- AVOID: Historical data from {email_year - 1} or earlier unless clearly marked as current
- Look for: "LTM EBITDA", "TTM EBITDA", "{email_year} EBITDA", "Adjusted EBITDA", "Current EBITDA"
- If multiple years shown, select the MOST RECENT period
- Convert to millions: "$5.2M" → 5.2, "$10M" → 10.0, "$3,600k" → 3.6
- Include "Adjusted EBITDA", "Pro Forma EBITDA", "Portfolio EBITDA" as separate options
- Confidence: explicit LTM/TTM with clear $ (0.95), current year (0.9), implied/estimated (0.6-0.8), old data (0.3)

FOR LOCATIONS (HIGH PRIORITY - BC FOCUS):
- **PRIORITIZE BC LOCATIONS**: Cities/regions in British Columbia should get HIGHEST confidence
- Look for: "headquarters", "HQ", "based in", "located in", "head office"
- BC cities to watch for: Vancouver, Victoria, Kelowna, Surrey, Burnaby, Richmond, Abbotsford, etc.
- Include specific cities (Vancouver) AND provinces (British Columbia, BC) as separate options
- Mark BC locations with 0.95 confidence if explicit, 0.85 if implied
- Non-BC locations: 0.7 for explicit, 0.5 for general mention
- Include target markets/service areas if mentioned

FOR COMPANY:
- Look in subject line first (Project names, code names)
- Check body for official company names
- Confidence: subject line (0.95), official name (0.9), variations (0.6)

FOR SECTOR:
- Provide up to 3 sector options (most specific to least specific)
- Be specific: "Quick Service Restaurants" not just "Food"
- Confidence: highly specific (0.95), general category (0.7), implied (0.5)

GENERAL:
- Include source: "email body", "subject line", "signature", etc.
- Include raw_text: the exact snippet where you found this
- Return empty arrays if no options found
- Proper JSON only (double quotes, no trailing commas)

EMAIL DATE: {email_data.date.strftime("%B %d, %Y") if email_data.date else "Unknown"}
EMAIL SUBJECT: {email_data.subject or "N/A"}

EMAIL BODY:
{body_text}

Return only the JSON object, no additional text or explanation."""

        return prompt
    
    def _parse_llm_response(self, response_text: str) -> Dict[str, Any]:
        """Parse JSON response from LLM.
        
        Args:
            response_text: Raw text response from LLM
            
        Returns:
            Parsed JSON dict
            
        Raises:
            json.JSONDecodeError: If response is not valid JSON
        """
        # Try to extract JSON from markdown code blocks if present
        if '```json' in response_text:
            start = response_text.find('```json') + 7
            end = response_text.find('```', start)
            response_text = response_text[start:end].strip()
        elif '```' in response_text:
            start = response_text.find('```') + 3
            end = response_text.find('```', start)
            response_text = response_text[start:end].strip()
        
        return json.loads(response_text)
    
    def parse_data(self, email_data: EmailData) -> InvestmentOpportunity:
        """Parse email data using GPT-4 to extract investment opportunity.
        
        Args:
            email_data: Extracted email data
            
        Returns:
            InvestmentOpportunity with extracted fields
        """
        # Extract source domain from sender
        source_domain = self.extract_domain(email_data.sender) if email_data.sender else None
        
        # Identify recipient
        recipient = email_data.recipients[0] if email_data.recipients else None
        
        # Build prompt and call OpenAI
        try:
            prompt = self._build_extraction_prompt(email_data)
            
            self.logger.debug(f"Calling OpenAI API with model: {self.model}")
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a precise data extraction assistant. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            
            # Extract response text
            response_text = response.choices[0].message.content
            self.logger.debug(f"LLM response: {response_text[:200]}...")
            
            # Parse JSON response
            extracted_data = self._parse_llm_response(response_text)
            
            # Parse options
            ebitda_options = []
            location_options = []
            company_options = []
            sector_options = []
            
            # Convert ebitda_options
            for opt in extracted_data.get('ebitda_options', []):
                if isinstance(opt, dict) and 'value' in opt:
                    ebitda_options.append(FieldOption(**opt))
            
            # Convert location_options
            for opt in extracted_data.get('location_options', []):
                if isinstance(opt, dict) and 'value' in opt:
                    location_options.append(FieldOption(**opt))
            
            # Convert company_options  
            for opt in extracted_data.get('company_options', []):
                if isinstance(opt, dict) and 'value' in opt:
                    company_options.append(FieldOption(**opt))
            
            # Convert sector_options
            for opt in extracted_data.get('sector_options', []):
                if isinstance(opt, dict) and 'value' in opt:
                    sector_options.append(FieldOption(**opt))
            
            # Use highest confidence options as primary values
            best_ebitda = max(ebitda_options, key=lambda x: x.confidence) if ebitda_options else None
            best_location = max(location_options, key=lambda x: x.confidence) if location_options else None
            best_company = max(company_options, key=lambda x: x.confidence) if company_options else None
            best_sector = max(sector_options, key=lambda x: x.confidence) if sector_options else None
            
            # Create InvestmentOpportunity
            opportunity = InvestmentOpportunity(
                source_domain=source_domain,
                recipient=recipient,
                hq_location=best_location.value if best_location else None,
                ebitda_millions=best_ebitda.value if best_ebitda else None,
                date=email_data.date,
                company_name=best_company.value if best_company else None,
                sector=best_sector.value if best_sector else None,
                raw_ebitda_text=best_ebitda.raw_text if best_ebitda else None,
                ebitda_options=ebitda_options,
                location_options=location_options,
                company_options=company_options,
                sector_options=sector_options,
            )
            
            self.logger.info(f"Extracted: EBITDA=${opportunity.ebitda_millions}M, Location={opportunity.hq_location}")
            
            return opportunity
            
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse LLM JSON response: {e}")
            # Return partial data
            return InvestmentOpportunity(
                source_domain=source_domain,
                recipient=recipient,
                date=email_data.date,
            )
        
        except Exception as e:
            self.logger.error(f"LLM parsing failed: {e}")
            # Return partial data
            return InvestmentOpportunity(
                source_domain=source_domain,
                recipient=recipient,
                date=email_data.date,
            )
    
    def parse(self, msg_path) -> ParserResult:
        """Parse a .msg file using LLM-based extraction.
        
        Overrides base method to set extraction_source correctly.
        
        Args:
            msg_path: Path to the .msg file
            
        Returns:
            ParserResult with extracted data
        """
        result = super().parse(msg_path)
        result.extraction_source = "body"
        return result

