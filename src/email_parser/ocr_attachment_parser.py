"""OCR + LLM attachment parser for PDF and image processing.

This module implements a parser that uses OCR to extract text from PDF
attachments, then uses LLM to extract structured data.
"""

import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytesseract
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


class OCRAttachmentParser(BaseParser):
    """Parser that uses OCR + LLM to extract data from PDF/image attachments.
    
    This parser:
    1. Converts PDF pages to images
    2. Applies OCR to extract text with bounding boxes
    3. Sends OCR text to LLM for structured extraction
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4-turbo-preview",
        temperature: float = 0.1,
        tesseract_cmd: Optional[str] = None,
    ):
        """Initialize OCR attachment parser.
        
        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: OpenAI model to use
            temperature: Temperature for generation
            tesseract_cmd: Path to tesseract executable (optional)
        """
        super().__init__(name="OCR-Attachment-Parser")
        
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise ValueError("OpenAI API key is required. Set OPENAI_API_KEY env var or pass api_key.")
        
        self.client = OpenAI(api_key=self.api_key)
        self.model = model
        self.temperature = temperature
        
        # Configure tesseract if custom path provided
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        elif os.getenv('TESSERACT_CMD'):
            pytesseract.pytesseract.tesseract_cmd = os.getenv('TESSERACT_CMD')
        
        self.logger.info(f"Initialized OCR parser with model: {model}")
    
    def _is_pdf_attachment(self, attachment: Attachment) -> bool:
        """Check if attachment is a PDF file.
        
        Args:
            attachment: Attachment object
            
        Returns:
            True if PDF, False otherwise
        """
        filename_lower = attachment.filename.lower()
        return (
            filename_lower.endswith('.pdf') or
            (attachment.content_type and 'pdf' in attachment.content_type.lower())
        )
    
    def _is_image_attachment(self, attachment: Attachment) -> bool:
        """Check if attachment is an image file.
        
        Args:
            attachment: Attachment object
            
        Returns:
            True if image, False otherwise
        """
        filename_lower = attachment.filename.lower()
        image_extensions = ['.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.gif']
        return (
            any(filename_lower.endswith(ext) for ext in image_extensions) or
            (attachment.content_type and 'image' in attachment.content_type.lower())
        )
    
    def _pdf_to_images(self, pdf_bytes: bytes) -> List[Image.Image]:
        """Convert PDF bytes to list of PIL images.
        
        Args:
            pdf_bytes: PDF file content as bytes
            
        Returns:
            List of PIL Image objects (one per page)
        """
        try:
            images = convert_from_bytes(pdf_bytes, dpi=200)
            self.logger.info(f"Converted PDF to {len(images)} images")
            return images
        except Exception as e:
            self.logger.error(f"PDF conversion failed: {e}")
            return []
    
    def _ocr_image(self, image: Image.Image, page_num: int = 0) -> Tuple[str, List[BoundingBox]]:
        """Apply OCR to extract text and bounding boxes from image.
        
        Args:
            image: PIL Image object
            page_num: Page number (0-indexed)
            
        Returns:
            Tuple of (extracted_text, bounding_boxes)
        """
        try:
            # Extract text
            text = pytesseract.image_to_string(image)
            
            # Extract bounding boxes with OCR data
            ocr_data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            
            bounding_boxes = []
            n_boxes = len(ocr_data['text'])
            
            for i in range(n_boxes):
                word = ocr_data['text'][i].strip()
                if word and int(ocr_data['conf'][i]) > 30:  # Confidence threshold
                    bbox = BoundingBox(
                        x=int(ocr_data['left'][i]),
                        y=int(ocr_data['top'][i]),
                        width=int(ocr_data['width'][i]),
                        height=int(ocr_data['height'][i]),
                        page=page_num,
                        confidence=float(ocr_data['conf'][i]) / 100.0,
                    )
                    bounding_boxes.append(bbox)
            
            self.logger.info(f"OCR extracted {len(text)} chars and {len(bounding_boxes)} boxes from page {page_num}")
            return text, bounding_boxes
            
        except Exception as e:
            self.logger.error(f"OCR failed for page {page_num}: {e}")
            return "", []
    
    def _process_pdf_attachment(self, attachment: Attachment) -> Tuple[str, Dict[str, List[BoundingBox]]]:
        """Process PDF attachment with OCR.
        
        Args:
            attachment: PDF attachment
            
        Returns:
            Tuple of (combined_text, bounding_boxes_dict)
        """
        images = self._pdf_to_images(attachment.content)
        
        if not images:
            return "", {}
        
        all_text = []
        all_boxes = {}
        
        # Process first 3 pages only (to save time)
        for page_num, image in enumerate(images[:3]):
            text, boxes = self._ocr_image(image, page_num)
            all_text.append(f"[Page {page_num + 1}]\n{text}")
            
            # Store boxes by field (will be populated later)
            if boxes:
                all_boxes[f"page_{page_num}"] = boxes
        
        combined_text = "\n\n".join(all_text)
        return combined_text, all_boxes
    
    def _process_image_attachment(self, attachment: Attachment) -> Tuple[str, Dict[str, List[BoundingBox]]]:
        """Process image attachment with OCR.
        
        Args:
            attachment: Image attachment
            
        Returns:
            Tuple of (text, bounding_boxes_dict)
        """
        try:
            image = Image.open(io.BytesIO(attachment.content))
            text, boxes = self._ocr_image(image, 0)
            
            boxes_dict = {"image": boxes} if boxes else {}
            return text, boxes_dict
            
        except Exception as e:
            self.logger.error(f"Image processing failed: {e}")
            return "", {}
    
    def _extract_with_llm(self, ocr_text: str) -> Dict[str, Any]:
        """Use LLM to extract structured data from OCR text.
        
        Args:
            ocr_text: Text extracted via OCR
            
        Returns:
            Dict with extracted fields
        """
        # Truncate if too long
        if len(ocr_text) > 10000:
            ocr_text = ocr_text[:10000] + "\n... [truncated]"
        
        prompt = f"""You are an expert at extracting structured information from investment teasers and pitch decks.

Extract the following fields from the OCR text below. Return ONLY a valid JSON object:

{{
  "hq_location": "string or null - Headquarters location",
  "ebitda_millions": number or null - EBITDA in millions,
  "company_name": "string or null - Company or project name",
  "sector": "string or null - Industry sector",
  "raw_ebitda_text": "string or null - Exact EBITDA text"
}}

Instructions:
- Look for financial metrics, especially EBITDA or Adjusted EBITDA
- Look for location mentions (city, state/province)
- Look for company/project names
- Return null for fields not found
- Ensure valid JSON format

OCR TEXT:
{ocr_text}

Return only the JSON object:"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a precise data extraction assistant. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature,
                max_tokens=4096,
            )
            
            response_text = response.choices[0].message.content
            
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
            self.logger.error(f"LLM extraction from OCR text failed: {e}")
            return {}
    
    def parse_data(self, email_data: EmailData) -> InvestmentOpportunity:
        """Parse email attachments using OCR + LLM.
        
        Args:
            email_data: Extracted email data
            
        Returns:
            InvestmentOpportunity with extracted fields
        """
        # Extract source and recipient from email metadata
        source_domain = self.extract_domain(email_data.sender) if email_data.sender else None
        recipient = email_data.recipients[0] if email_data.recipients else None
        
        # Process all PDF and image attachments
        all_ocr_text = []
        all_bounding_boxes = {}
        
        for attachment in email_data.attachments:
            if self._is_pdf_attachment(attachment):
                self.logger.info(f"Processing PDF attachment: {attachment.filename}")
                text, boxes = self._process_pdf_attachment(attachment)
                if text:
                    all_ocr_text.append(text)
                    all_bounding_boxes.update(boxes)
            
            elif self._is_image_attachment(attachment):
                self.logger.info(f"Processing image attachment: {attachment.filename}")
                text, boxes = self._process_image_attachment(attachment)
                if text:
                    all_ocr_text.append(text)
                    all_bounding_boxes.update(boxes)
        
        if not all_ocr_text:
            self.logger.warning("No text extracted from attachments")
            return InvestmentOpportunity(
                source_domain=source_domain,
                recipient=recipient,
                date=email_data.date,
            )
        
        # Combine all OCR text
        combined_text = "\n\n".join(all_ocr_text)
        
        # Extract structured data using LLM
        extracted_data = self._extract_with_llm(combined_text)
        
        # Create opportunity
        opportunity = InvestmentOpportunity(
            source_domain=source_domain,
            recipient=recipient,
            hq_location=extracted_data.get('hq_location'),
            ebitda_millions=extracted_data.get('ebitda_millions'),
            date=email_data.date,
            company_name=extracted_data.get('company_name'),
            sector=extracted_data.get('sector'),
            raw_ebitda_text=extracted_data.get('raw_ebitda_text'),
            bounding_boxes=all_bounding_boxes,
        )
        
        self.logger.info(
            f"Extracted from attachments: EBITDA=${opportunity.ebitda_millions}M, "
            f"Location={opportunity.hq_location}"
        )
        
        return opportunity
    
    def parse(self, msg_path: Path) -> ParserResult:
        """Parse a .msg file using OCR on attachments.
        
        Args:
            msg_path: Path to the .msg file
            
        Returns:
            ParserResult with extracted data
        """
        result = super().parse(msg_path)
        result.extraction_source = "attachment"
        return result

