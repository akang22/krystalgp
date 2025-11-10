"""OCR + NER attachment parser combining OCR with traditional NLP.

This module implements a parser that uses OCR to extract text from PDF
attachments, then uses NER and regex (not LLM) for extraction.
"""

import io
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytesseract
import spacy
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
from email_parser.utils import (
    extract_canadian_provinces,
    extract_ebitda,
    extract_location,
    normalize_text,
)


class OCRNERParser(BaseParser):
    """Parser that uses OCR + NER/regex to extract data from PDF/image attachments.
    
    This parser:
    1. Converts PDF pages to images
    2. Applies OCR to extract text with bounding boxes
    3. Uses spaCy NER and regex patterns for extraction (NO LLM calls)
    
    Advantages:
    - No API costs (completely free)
    - Works offline
    - Faster than OCR + LLM approach
    - Still gets bounding boxes
    """
    
    def __init__(
        self,
        tesseract_cmd: Optional[str] = None,
        spacy_model: str = "en_core_web_sm",
    ):
        """Initialize OCR + NER parser.
        
        Args:
            tesseract_cmd: Path to tesseract executable (optional)
            spacy_model: spaCy model name
        """
        super().__init__(name="OCR-NER-Parser")
        
        # Configure tesseract
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        else:
            # Auto-detect tesseract
            tesseract_path = shutil.which('tesseract')
            if tesseract_path:
                pytesseract.pytesseract.tesseract_cmd = tesseract_path
                self.logger.info(f"Found tesseract at: {tesseract_path}")
        
        # Load spaCy model
        try:
            self.nlp = spacy.load(spacy_model)
        except OSError:
            self.logger.warning(f"spaCy model '{spacy_model}' not found. Attempting to download...")
            try:
                from spacy.cli import download
                download(spacy_model)
                self.nlp = spacy.load(spacy_model)
            except Exception as e:
                self.logger.error(f"Failed to download spaCy model: {e}")
                raise RuntimeError(
                    f"spaCy model '{spacy_model}' not installed. "
                    f"Please install: python -m spacy download {spacy_model}"
                )
        
        self.logger.info(f"Initialized OCR+NER parser with spaCy: {spacy_model}")
    
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
    
    def _pdf_to_images(self, pdf_bytes: bytes) -> List[Image.Image]:
        """Convert PDF bytes to list of PIL images."""
        try:
            images = convert_from_bytes(pdf_bytes, dpi=200)
            self.logger.info(f"Converted PDF to {len(images)} images")
            return images
        except Exception as e:
            self.logger.error(f"PDF conversion failed: {e}")
            return []
    
    def _ocr_image(self, image: Image.Image, page_num: int = 0) -> Tuple[str, List[BoundingBox]]:
        """Apply OCR to extract text and bounding boxes from image."""
        try:
            # Extract text
            text = pytesseract.image_to_string(image)
            
            # Extract bounding boxes
            ocr_data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            
            bounding_boxes = []
            n_boxes = len(ocr_data['text'])
            
            for i in range(n_boxes):
                word = ocr_data['text'][i].strip()
                if word and int(ocr_data['conf'][i]) > 30:
                    bbox = BoundingBox(
                        x=int(ocr_data['left'][i]),
                        y=int(ocr_data['top'][i]),
                        width=int(ocr_data['width'][i]),
                        height=int(ocr_data['height'][i]),
                        page=page_num,
                        confidence=float(ocr_data['conf'][i]) / 100.0,
                    )
                    bounding_boxes.append(bbox)
            
            self.logger.info(f"OCR extracted {len(text)} chars from page {page_num}")
            return text, bounding_boxes
            
        except Exception as e:
            self.logger.error(f"OCR failed for page {page_num}: {e}")
            return "", []
    
    def _extract_from_text_ner(self, text: str) -> Dict[str, any]:
        """Extract information from OCR text using NER and regex.
        
        Args:
            text: OCR-extracted text
            
        Returns:
            Dict with extracted fields
        """
        # Normalize text
        text = normalize_text(text)
        
        # Extract EBITDA with regex
        ebitda_result = extract_ebitda(text)
        ebitda_millions = ebitda_result[0] if ebitda_result else None
        raw_ebitda_text = ebitda_result[1] if ebitda_result else None
        
        # Extract location
        hq_location = extract_location(text)
        
        # Use NER for additional extraction
        doc = self.nlp(text[:2000])  # Process first 2000 chars
        
        # Extract organizations (potential company names)
        company_names = [ent.text for ent in doc.ents if ent.label_ == 'ORG']
        company_name = company_names[0] if company_names else None
        
        # Extract locations from NER
        if not hq_location:
            locations = [ent.text for ent in doc.ents if ent.label_ in ['GPE', 'LOC']]
            # Check for Canadian provinces
            provinces = extract_canadian_provinces(text)
            
            # Prioritize locations with provinces
            for loc in locations:
                for prov in provinces:
                    if prov in loc:
                        hq_location = loc
                        break
                if hq_location:
                    break
            
            # Fall back to first location
            if not hq_location and locations:
                hq_location = locations[0]
        
        return {
            'hq_location': hq_location,
            'ebitda_millions': ebitda_millions,
            'company_name': company_name,
            'raw_ebitda_text': raw_ebitda_text,
        }
    
    def _process_pdf_attachment(self, attachment: Attachment) -> Tuple[str, Dict[str, any], Dict[str, List[BoundingBox]]]:
        """Process PDF attachment with OCR.
        
        Args:
            attachment: PDF attachment
            
        Returns:
            Tuple of (combined_text, extracted_data, bounding_boxes_dict)
        """
        images = self._pdf_to_images(attachment.content)
        
        if not images:
            return "", {}, {}
        
        all_text = []
        all_boxes = {}
        
        # Process first 3 pages
        for page_num, image in enumerate(images[:3]):
            text, boxes = self._ocr_image(image, page_num)
            all_text.append(text)
            
            if boxes:
                all_boxes[f"page_{page_num}"] = boxes
        
        combined_text = "\n\n".join(all_text)
        
        # Extract using NER
        extracted_data = self._extract_from_text_ner(combined_text)
        
        return combined_text, extracted_data, all_boxes
    
    def _process_image_attachment(self, attachment: Attachment) -> Tuple[str, Dict[str, any], Dict[str, List[BoundingBox]]]:
        """Process image attachment with OCR."""
        try:
            image = Image.open(io.BytesIO(attachment.content))
            text, boxes = self._ocr_image(image, 0)
            
            extracted_data = self._extract_from_text_ner(text)
            boxes_dict = {"image": boxes} if boxes else {}
            
            return text, extracted_data, boxes_dict
            
        except Exception as e:
            self.logger.error(f"Image processing failed: {e}")
            return "", {}, {}
    
    def parse_data(self, email_data: EmailData) -> InvestmentOpportunity:
        """Parse email attachments using OCR + NER.
        
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
        all_bounding_boxes = {}
        
        for attachment in email_data.attachments:
            if self._is_pdf_attachment(attachment):
                self.logger.info(f"Processing PDF with OCR+NER: {attachment.filename}")
                text, data, boxes = self._process_pdf_attachment(attachment)
                if data:
                    all_extracted_data.append(data)
                    all_bounding_boxes.update(boxes)
            
            elif self._is_image_attachment(attachment):
                self.logger.info(f"Processing image with OCR+NER: {attachment.filename}")
                text, data, boxes = self._process_image_attachment(attachment)
                if data:
                    all_extracted_data.append(data)
                    all_bounding_boxes.update(boxes)
        
        if not all_extracted_data:
            self.logger.warning("No data extracted from attachments")
            return InvestmentOpportunity(
                source_domain=source_domain,
                recipient=recipient,
                date=email_data.date,
            )
        
        # Merge extracted data (take first non-None value for each field)
        merged_data = {}
        for data in all_extracted_data:
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
            raw_ebitda_text=merged_data.get('raw_ebitda_text'),
            bounding_boxes=all_bounding_boxes,
        )
        
        self.logger.info(
            f"OCR+NER extracted: EBITDA=${opportunity.ebitda_millions}M, "
            f"Location={opportunity.hq_location}"
        )
        
        return opportunity
    
    def parse(self, msg_path: Path) -> ParserResult:
        """Parse a .msg file using OCR+NER on attachments.
        
        Args:
            msg_path: Path to the .msg file
            
        Returns:
            ParserResult with extracted data
        """
        result = super().parse(msg_path)
        result.extraction_source = "attachment"
        return result

