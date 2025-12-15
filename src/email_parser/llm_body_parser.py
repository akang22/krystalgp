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

from email_parser.base import (BaseParser, EmailData, FieldOption,
                               InvestmentOpportunity, ParserResult)

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

        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key is required. Set OPENAI_API_KEY env var or pass api_key."
            )

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

**IMPORTANT: The "description" field is MANDATORY and must be generated from the email body content, NOT the subject line.**

Return ONLY a valid JSON object with these exact fields:

{{
  "description": "EXACTLY 2-5 words describing the business. Count your words! Examples: 'Leading Canadian Footwear Brand' (4 words), 'Regional Airline servicing small towns in BC' (5 words), 'LED ad technology' (3 words), 'Portfolio of F&B brands' (4 words). NO MORE THAN 5 WORDS. DO NOT use email subject.",
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
  "sector": "Retail"
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
- Use EXACTLY ONE of these sector categories (single word or two-word phrase):
  - Retail
  - Consumer Services
  - Building Products
  - Transportation Services
  - Healthcare
  - Industrial Products
  - Business Services
  - Wholesale
  - Electronics
  - Transportation Products
  - Other (use only if none of the above fit)
- Return a single sector string value (not an array)
- Match the company's primary business to the closest category

FOR DESCRIPTION (REQUIRED - MUST BE INCLUDED):
- **CRITICAL**: This field is REQUIRED. Generate EXACTLY 2-5 words from email body (NOT subject)
- **WORD COUNT RULE**: Count your words! The description MUST be between 2 and 5 words total. NO MORE, NO LESS.
- **STRICT FORMAT**: Use only 2-5 words separated by spaces. No sentences, no periods, no commas.
- Examples (count the words):
  * "Leading Canadian Footwear Brand" = 4 words ✓
  * "Regional Airline servicing small towns in BC" = 5 words ✓
  * "LED ad technology" = 3 words ✓
  * "Portfolio of F&B brands" = 4 words ✓
  * "Frozen seafood importer" = 3 words ✓
- Focus on what the company does in the fewest words possible
- Extract from main email content, not signatures or subject lines
- DO NOT use the email subject as the description
- If you generate more than 5 words, you have FAILED. Count and trim to 5 words maximum.

GENERAL:
- **DO NOT extract from email signatures**: Ignore any information found in email signatures (contact details, disclaimers, "Sent from" messages, etc.)
- Include source: "email body", "subject line", etc. (NEVER use "signature" as a source)
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
        if "```json" in response_text:
            start = response_text.find("```json") + 7
            end = response_text.find("```", start)
            response_text = response_text[start:end].strip()
        elif "```" in response_text:
            start = response_text.find("```") + 3
            end = response_text.find("```", start)
            response_text = response_text[start:end].strip()

        return json.loads(response_text)

    def parse_data(self, email_data: EmailData) -> InvestmentOpportunity:
        """Parse email data using GPT-4 to extract investment opportunity.

        Args:
            email_data: Extracted email data

        Returns:
            InvestmentOpportunity with extracted fields
        """
        # Extract source domain from original sender (for forwards)
        original_sender = self.extract_original_sender(email_data)
        source_domain = self.extract_domain(original_sender) if original_sender else None

        # Identify recipient
        recipient = email_data.recipients[0] if email_data.recipients else None

        # Build prompt and call OpenAI
        try:
            prompt = self._build_extraction_prompt(email_data)

            self.logger.debug(f"Calling OpenAI API with model: {self.model}")

            # Use structured output if available (GPT-4o and newer models support this)
            # This ensures the description field is always included
            try:
                # Try with response_format for structured output (GPT-4o, GPT-4-turbo)
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a precise data extraction assistant. Return only valid JSON with all required fields including 'description'.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    response_format={"type": "json_object"},  # Force JSON output
                )
            except Exception as e:
                # Fallback if response_format not supported
                self.logger.warning(f"Structured output not supported, using standard format: {e}")
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a precise data extraction assistant. Return only valid JSON with all required fields including 'description'.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )

            # Extract response text
            response_text = response.choices[0].message.content
            self.logger.debug(f"LLM response: {response_text[:500]}...")

            # Parse JSON response
            extracted_data = self._parse_llm_response(response_text)

            # Extract description - check multiple possible keys
            description = None
            if "description" in extracted_data:
                description = extracted_data.get("description", "").strip() or None
            elif "business_description" in extracted_data:
                description = extracted_data.get("business_description", "").strip() or None

            if description:
                self.logger.info(f"✓ Extracted description: {description}")
            else:
                self.logger.warning("⚠️ No description found in LLM response")
                self.logger.warning(f"Available keys in response: {list(extracted_data.keys())}")
                self.logger.warning(f"Full response preview: {str(extracted_data)[:500]}")

                # Fallback: Try to generate a simple description from company/sector if available
                # This is a last resort if LLM didn't provide description
                company = (
                    extracted_data.get("company_options", [{}])[0].get("value", "")
                    if extracted_data.get("company_options")
                    else None
                )
                sector = (
                    extracted_data.get("sector_options", [{}])[0].get("value", "")
                    if extracted_data.get("sector_options")
                    else None
                )
                if company or sector:
                    description = f"{company or 'Company'} - {sector or 'Business'}"
                    self.logger.info(f"Generated fallback description: {description}")

            # Parse options
            ebitda_options = []
            location_options = []
            company_options = []
            sector_options = []

            # Convert ebitda_options and filter out signature sources
            for opt in extracted_data.get("ebitda_options", []):
                if isinstance(opt, dict) and "value" in opt:
                    source = opt.get("source", "").lower()
                    # Filter out any results from signatures
                    if "signature" not in source:
                        ebitda_options.append(FieldOption(**opt))

            # Convert location_options and filter out signature sources
            for opt in extracted_data.get("location_options", []):
                if isinstance(opt, dict) and "value" in opt:
                    source = opt.get("source", "").lower()
                    # Filter out any results from signatures
                    if "signature" not in source:
                        location_options.append(FieldOption(**opt))

            # Convert company_options and filter out signature sources
            for opt in extracted_data.get("company_options", []):
                if isinstance(opt, dict) and "value" in opt:
                    source = opt.get("source", "").lower()
                    # Filter out any results from signatures
                    if "signature" not in source:
                        company_options.append(FieldOption(**opt))

            # Sector is now a single string value, not an array
            # Handle both old format (sector_options array) and new format (sector string)
            valid_sectors = {
                "Retail", "Consumer Services", "Building Products", "Transportation Services",
                "Healthcare", "Industrial Products", "Business Services", "Wholesale",
                "Electronics", "Transportation Products", "Other"
            }
            
            best_sector = None
            sector_options = []
            
            # Check for new format (single sector string)
            if "sector" in extracted_data:
                sector_value = extracted_data.get("sector", "").strip()
                if sector_value in valid_sectors:
                    best_sector = sector_value
                else:
                    # If not valid, default to "Other"
                    best_sector = "Other"
                    self.logger.warning(f"Invalid sector '{sector_value}', defaulting to 'Other'")
            # Fallback to old format (sector_options array) for backwards compatibility
            elif "sector_options" in extracted_data:
                for opt in extracted_data.get("sector_options", []):
                    if isinstance(opt, dict) and "value" in opt:
                        source = opt.get("source", "").lower()
                        # Filter out any results from signatures
                        if "signature" not in source:
                            sector_options.append(FieldOption(**opt))
                
                if sector_options:
                    # Find first valid sector category
                    for opt in sorted(sector_options, key=lambda x: x.confidence, reverse=True):
                        if opt.value in valid_sectors:
                            best_sector = opt.value
                            break
                    # If no valid category found, default to "Other"
                    if not best_sector:
                        best_sector = "Other"
                        self.logger.warning("No valid sector found in options, defaulting to 'Other'")

            # Use highest confidence options as primary values
            best_ebitda = (
                max(ebitda_options, key=lambda x: x.confidence) if ebitda_options else None
            )
            best_location = (
                max(location_options, key=lambda x: x.confidence) if location_options else None
            )
            best_company = (
                max(company_options, key=lambda x: x.confidence) if company_options else None
            )

            # Create InvestmentOpportunity
            opportunity = InvestmentOpportunity(
                source_domain=source_domain,
                recipient=recipient,
                hq_location=best_location.value if best_location else None,
                ebitda_millions=best_ebitda.value if best_ebitda else None,
                date=email_data.date,
                company_name=best_company.value if best_company else None,
                sector=best_sector if isinstance(best_sector, str) else (best_sector.value if best_sector else None),
                description=description,
                raw_ebitda_text=best_ebitda.raw_text if best_ebitda else None,
                ebitda_options=ebitda_options,
                location_options=location_options,
                company_options=company_options,
                sector_options=sector_options,
            )

            self.logger.info(
                f"Extracted: EBITDA=${opportunity.ebitda_millions}M, Location={opportunity.hq_location}"
            )

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
