"""Layout-aware attachment parser using vision models.

This module implements a parser that uses GPT-4-Vision to directly analyze
PDF/image attachments with layout awareness.
"""

import base64
import io
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI
from pdf2image import convert_from_bytes
from PIL import Image

from email_parser.base import (
    Attachment,
    BaseParser,
    BoundingBox,
    EmailData,
    InvestmentOpportunity,
    ParserResult,
    VALID_SECTORS,
)

# Load environment variables from .env file
load_dotenv()


class LayoutLLMParser(BaseParser):
    """Parser that uses GPT-4-Vision for layout-aware document understanding.
    
    This parser directly sends images/PDFs to GPT-4-Vision which can:
    - Understand document structure and layout
    - Extract information from tables and charts
    - Interpret visual elements
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o",  # Updated from deprecated gpt-4-vision-preview
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ):
        """Initialize layout-aware LLM parser.
        
        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Vision model to use (gpt-4-vision-preview, gpt-4o, etc.)
            temperature: Temperature for generation
            max_tokens: Maximum tokens in response
        """
        super().__init__(name="Layout-LLM-Parser")
        
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY env var or pass api_key.")
        
        self.client = OpenAI(api_key=self.api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        self.logger.info(f"Initialized Layout LLM parser with model: {model}")
    
    def _is_pdf_attachment(self, attachment: Attachment) -> bool:
        """Check if attachment is a PDF file."""
        filename_lower = attachment.filename.lower()
        return (
            filename_lower.endswith('.pdf') or
            (attachment.content_type and 'pdf' in attachment.content_type.lower())
        )
    
    def _is_image_attachment(self, attachment: Attachment) -> bool:
        """Check if attachment is an image file."""
        filename_lower = attachment.filename.lower()
        image_extensions = ['.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.gif']
        return (
            any(filename_lower.endswith(ext) for ext in image_extensions) or
            (attachment.content_type and 'image' in attachment.content_type.lower())
        )
    
    def _pdf_to_images(self, pdf_bytes: bytes, max_pages: int = 3) -> List[Image.Image]:
        """Convert PDF bytes to list of PIL images.
        
        Args:
            pdf_bytes: PDF file content
            max_pages: Maximum number of pages to process
            
        Returns:
            List of PIL Image objects
        """
        try:
            images = convert_from_bytes(pdf_bytes, dpi=150)
            self.logger.info(f"Converted PDF to {len(images)} images")
            return images[:max_pages]
        except Exception as e:
            self.logger.error(f"PDF conversion failed: {e}")
            return []
    
    def _image_to_base64(self, image: Image.Image, format: str = "PNG") -> str:
        """Convert PIL Image to base64 string.
        
        Args:
            image: PIL Image object
            format: Image format (PNG, JPEG, etc.)
            
        Returns:
            Base64 encoded string
        """
        buffered = io.BytesIO()
        image.save(buffered, format=format)
        img_bytes = buffered.getvalue()
        return base64.b64encode(img_bytes).decode('utf-8')
    
    def _bytes_to_base64(self, content: bytes) -> str:
        """Convert bytes to base64 string.
        
        Args:
            content: File content as bytes
            
        Returns:
            Base64 encoded string
        """
        return base64.b64encode(content).decode('utf-8')
    
    def _extract_with_vision(self, images: List[Image.Image], email_date: Optional[datetime] = None) -> Dict[str, Any]:
        """Use GPT-4-Vision to extract data from images.
        
        Args:
            images: List of PIL Images to analyze
            email_date: Email date for temporal context
            
        Returns:
            Dict with extracted fields
        """
        email_year = email_date.year if email_date else datetime.now().year
        
        prompt_text = f"""You are an expert at analyzing investment teasers, pitch decks, and confidential information memorandums (CIMs) for a BC (British Columbia, Canada) focused private equity firm.

**CONTEXT:**
- Document is from {email_year}
- Firm prioritizes BC-based companies
- Need MOST RECENT EBITDA (TTM, LTM, or {email_year})

Analyze this document and extract the following information. Return ONLY a valid JSON object:

{{
  "description": "string or null - EXACTLY 2-5 words describing the business opportunity. Count your words! Examples: 'Leading Canadian Fiberglass Manufacturer' (4 words), 'Regional Distribution Business' (3 words), 'Industrial Products Company' (3 words). NO MORE THAN 5 WORDS.",
  "hq_location": "string or null - Headquarters location OR operating region (city, state/province, country, or region like 'Western Canada')",
  "ebitda_millions": number or null - EBITDA in millions of dollars,
  "company_name": "string or null - Company or project name",
  "sector": "string or null - Industry sector or business type",
  "raw_ebitda_text": "string or null - Exact text showing EBITDA figure"
}}

**CRITICAL INSTRUCTIONS:**

FOR DESCRIPTION (REQUIRED - MUST BE INCLUDED IF FOUND):
- **WORD COUNT RULE**: Count your words! The description MUST be between 2 and 5 words total. NO MORE, NO LESS.
- Look for business descriptions in: document title, executive summary, first paragraph, "About" sections, cover page
- Examples: "Leading Canadian Fiberglass Manufacturer" (4 words), "Regional Distribution Business" (3 words), "Industrial Products Company" (3 words)
- Extract the core business description, NOT the investment opportunity description
- If you find phrases like "Opportunity to acquire a leading Canadian fiberglass manufacturer", extract "Leading Canadian Fiberglass Manufacturer" (4 words)
- DO NOT include words like "opportunity", "acquire", "investment" - focus on WHAT the business IS

FOR EBITDA:
- PRIORITIZE: TTM, LTM, or {email_year} EBITDA (not {email_year - 1})
- Look in financial tables, executive summaries, key metrics
- If multiple years shown, select MOST RECENT
- Look for: "Adjusted EBITDA", "Portfolio EBITDA", "LTM EBITDA"
- Convert to millions: $5.2M → 5.2, $10,000K → 10.0, C$3.6M → 3.6

FOR LOCATIONS (IMPORTANT - LOOK FOR OPERATING REGIONS TOO):
- **PRIORITIZE**: Look for BOTH headquarters AND operating regions/scope of operations
- **HEADQUARTERS**: Look for "HQ:", "Headquarters:", "Location:", "Based in", headers, footers
- **OPERATING REGIONS**: Look for "operating in", "serves", "scope of operations", "service area", "markets", "geographic presence"
- **WESTERN CANADA DETECTION**: If document mentions "Western Canada", "Western Canadian", "West Coast", "BC and Alberta", or similar regional terms, use "Western Canada" as the location
- **PRIORITIZE BC cities**: Vancouver, Victoria, Surrey, Burnaby, Richmond, Kelowna
- **REGIONAL TERMS**: If no specific city but mentions "Western Canada", "Western Canadian", "West Coast", use that as location
- If company operates in Western Canada (BC/Alberta) but HQ is elsewhere, still note "Western Canada" as location
- Include specific city and province if found, OR use regional descriptor if that's what's mentioned

FOR COMPANY:
- Check document header/title/cover page
- Look for project code name or official company name

FOR SECTOR (CRITICAL - MUST USE EXACT VALUES):
- **MANDATORY**: You MUST use EXACTLY ONE of these sector categories. Use the EXACT spelling and capitalization shown below:
  - Wholesale
  - Transportation Services
  - Transportation Products
  - Retail
  - Other
  - Industrial Products
  - Healthcare
  - Electronics
  - Consumer Services
  - Business Services
  - Building Products
  - Agriculture / Forestry
- **STRICT RULE**: Return ONLY one of these exact values. Do NOT create variations, abbreviations, or new categories.
- Match the company's primary business to the closest category from this list
- If none fit exactly, use "Other"

Return only the JSON object, no additional text."""

        try:
            # Build messages with images
            content = [{"type": "text", "text": prompt_text}]
            
            # Add up to 3 images
            for idx, image in enumerate(images[:3]):
                base64_image = self._image_to_base64(image)
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{base64_image}",
                        "detail": "high"  # Use high detail for better extraction
                    }
                })
                self.logger.debug(f"Added image {idx + 1} to vision request")
            
            # Call vision API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": content
                    }
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            
            response_text = response.choices[0].message.content
            self.logger.debug(f"Vision response: {response_text[:200]}...")
            
            # Parse JSON
            if '```json' in response_text:
                start = response_text.find('```json') + 7
                end = response_text.find('```', start)
                response_text = response_text[start:end].strip()
            elif '```' in response_text:
                start = response_text.find('```') + 3
                end = response_text.find('```', start)
                response_text = response_text[start:end].strip()
            
            return json.loads(response_text)
            
        except Exception as e:
            self.logger.error(f"Vision extraction failed: {e}")
            return {}
    
    def _process_pdf_attachment(self, attachment: Attachment, email_date: Optional[datetime] = None) -> Dict[str, Any]:
        """Process PDF attachment with vision model.
        
        Args:
            attachment: PDF attachment
            email_date: Email date for temporal context
            
        Returns:
            Dict with extracted data
        """
        images = self._pdf_to_images(attachment.content)
        
        if not images:
            self.logger.warning(f"No images extracted from PDF: {attachment.filename}")
            return {}
        
        return self._extract_with_vision(images, email_date)
    
    def _process_image_attachment(self, attachment: Attachment, email_date: Optional[datetime] = None) -> Dict[str, Any]:
        """Process image attachment with vision model.
        
        Args:
            attachment: Image attachment
            email_date: Email date for temporal context
            
        Returns:
            Dict with extracted data
        """
        try:
            image = Image.open(io.BytesIO(attachment.content))
            return self._extract_with_vision([image], email_date)
        except Exception as e:
            self.logger.error(f"Image processing failed: {e}")
            return {}
    
    def parse_data(self, email_data: EmailData) -> InvestmentOpportunity:
        """Parse email attachments using vision-based LLM.
        
        Args:
            email_data: Extracted email data
            
        Returns:
            InvestmentOpportunity with extracted fields
        """
        # Extract source and recipient from email metadata
        original_sender = self.extract_original_sender(email_data)
        source_domain = self.extract_domain(original_sender) if original_sender else None
        recipient = email_data.recipients[0] if email_data.recipients else None
        
        # Process attachments
        all_extracted_data = []
        
        for attachment in email_data.attachments:
            if self._is_pdf_attachment(attachment):
                self.logger.info(f"Processing PDF with vision: {attachment.filename}")
                data = self._process_pdf_attachment(attachment, email_data.date)
                if data:
                    all_extracted_data.append(data)
            
            elif self._is_image_attachment(attachment):
                self.logger.info(f"Processing image with vision: {attachment.filename}")
                data = self._process_image_attachment(attachment, email_data.date)
                if data:
                    all_extracted_data.append(data)
        
        if not all_extracted_data:
            self.logger.warning("No data extracted from attachments")
            return InvestmentOpportunity(
                source_domain=source_domain,
                recipient=recipient,
                date=email_data.date,
            )
        
        # Merge extracted data (prioritize first attachment)
        merged_data = all_extracted_data[0]
        
        # Fill in missing fields from other attachments
        for data in all_extracted_data[1:]:
            for key, value in data.items():
                if not merged_data.get(key) and value:
                    merged_data[key] = value

        # Validate and normalize sector
        sector = merged_data.get('sector', '').strip() if merged_data.get('sector') else None
        if sector and sector not in VALID_SECTORS:
            self.logger.warning(f"Invalid sector '{sector}' from Layout parser, defaulting to 'Other'")
            sector = "Other"

        # Extract and validate description
        description = merged_data.get('description', '').strip() if merged_data.get('description') else None
        if description:
            word_count = len(description.split())
            if word_count < 2 or word_count > 5:
                self.logger.warning(f"Description '{description}' has {word_count} words (should be 2-5), truncating/adjusting")
                # Try to fix: if too long, take first 5 words; if too short, use as-is (might be valid)
                words = description.split()
                if len(words) > 5:
                    description = " ".join(words[:5])
                    self.logger.info(f"Truncated description to: {description}")
            self.logger.info(f"✓ Extracted description ({len(description.split())} words): {description}")

        # Create opportunity
        opportunity = InvestmentOpportunity(
            source_domain=source_domain,
            recipient=recipient,
            hq_location=merged_data.get('hq_location'),
            ebitda_millions=merged_data.get('ebitda_millions'),
            date=email_data.date,
            company_name=merged_data.get('company_name'),
            sector=sector,
            description=description,
            raw_ebitda_text=merged_data.get('raw_ebitda_text'),
        )
        
        self.logger.info(
            f"Vision extracted: EBITDA=${opportunity.ebitda_millions}M, "
            f"Location={opportunity.hq_location}, Company={opportunity.company_name}"
        )
        
        return opportunity
    
    def parse(self, msg_path: Path) -> ParserResult:
        """Parse a .msg file using vision-based extraction on attachments.
        
        Args:
            msg_path: Path to the .msg file
            
        Returns:
            ParserResult with extracted data
        """
        result = super().parse(msg_path)
        result.extraction_source = "attachment"
        return result

