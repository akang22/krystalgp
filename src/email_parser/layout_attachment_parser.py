"""Layout-aware attachment parser using vision models.

This module implements a parser that uses GPT-4-Vision to directly analyze
PDF/image attachments with layout awareness.
"""

import base64
import io
import json
import os
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
        model: str = "gpt-4-vision-preview",
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
    
    def _extract_with_vision(self, images: List[Image.Image]) -> Dict[str, Any]:
        """Use GPT-4-Vision to extract data from images.
        
        Args:
            images: List of PIL Images to analyze
            
        Returns:
            Dict with extracted fields
        """
        prompt_text = """You are an expert at analyzing investment teasers, pitch decks, and confidential information memorandums (CIMs).

Analyze this document and extract the following information. Return ONLY a valid JSON object:

{
  "hq_location": "string or null - Headquarters location (city, state/province, country)",
  "ebitda_millions": number or null - EBITDA in millions of dollars,
  "company_name": "string or null - Company or project name",
  "sector": "string or null - Industry sector or business type",
  "raw_ebitda_text": "string or null - Exact text showing EBITDA figure"
}

Instructions:
- Look for financial tables, executive summaries, and key metrics sections
- EBITDA may be labeled as "EBITDA", "Adjusted EBITDA", "LTM EBITDA", etc.
- Convert to millions (e.g., $5.2M → 5.2, $10,000K → 10.0)
- For location, check headers, footers, company overview sections
- Return null for fields you cannot find
- Ensure proper JSON formatting

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
    
    def _process_pdf_attachment(self, attachment: Attachment) -> Dict[str, Any]:
        """Process PDF attachment with vision model.
        
        Args:
            attachment: PDF attachment
            
        Returns:
            Dict with extracted data
        """
        images = self._pdf_to_images(attachment.content)
        
        if not images:
            self.logger.warning(f"No images extracted from PDF: {attachment.filename}")
            return {}
        
        return self._extract_with_vision(images)
    
    def _process_image_attachment(self, attachment: Attachment) -> Dict[str, Any]:
        """Process image attachment with vision model.
        
        Args:
            attachment: Image attachment
            
        Returns:
            Dict with extracted data
        """
        try:
            image = Image.open(io.BytesIO(attachment.content))
            return self._extract_with_vision([image])
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
        source_domain = self.extract_domain(email_data.sender) if email_data.sender else None
        recipient = email_data.recipients[0] if email_data.recipients else None
        
        # Process attachments
        all_extracted_data = []
        
        for attachment in email_data.attachments:
            if self._is_pdf_attachment(attachment):
                self.logger.info(f"Processing PDF with vision: {attachment.filename}")
                data = self._process_pdf_attachment(attachment)
                if data:
                    all_extracted_data.append(data)
            
            elif self._is_image_attachment(attachment):
                self.logger.info(f"Processing image with vision: {attachment.filename}")
                data = self._process_image_attachment(attachment)
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
        
        # Create opportunity
        opportunity = InvestmentOpportunity(
            source_domain=source_domain,
            recipient=recipient,
            hq_location=merged_data.get('hq_location'),
            ebitda_millions=merged_data.get('ebitda_millions'),
            date=email_data.date,
            company_name=merged_data.get('company_name'),
            sector=merged_data.get('sector'),
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

