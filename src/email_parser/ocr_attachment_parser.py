"""OCR + LLM attachment parser for PDF and image processing.

This module implements a parser that uses OCR to extract text from PDF
attachments, then uses LLM to extract structured data.

Updated: 2025-11-11 - Fixed _extract_with_llm signature to accept email_date parameter
"""

import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytesseract
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

        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key is required. Set OPENAI_API_KEY env var or pass api_key."
            )

        self.client = OpenAI(api_key=self.api_key)
        self.model = model
        self.temperature = temperature

        # Configure tesseract path and verify installation
        import platform
        import shutil

        tesseract_found = False
        tesseract_path = None

        if tesseract_cmd:
            if os.path.exists(tesseract_cmd) or shutil.which(tesseract_cmd):
                tesseract_path = tesseract_cmd
                tesseract_found = True
                self.logger.info(f"Using tesseract at: {tesseract_path}")
            else:
                self.logger.warning(f"Specified tesseract path not found: {tesseract_cmd}")
        elif os.getenv("TESSERACT_CMD"):
            tesseract_env = os.getenv("TESSERACT_CMD")
            if os.path.exists(tesseract_env) or shutil.which(tesseract_env):
                tesseract_path = tesseract_env
                tesseract_found = True
                self.logger.info(f"Using tesseract from TESSERACT_CMD: {tesseract_path}")
            else:
                self.logger.warning(f"TESSERACT_CMD path not found: {tesseract_env}")
        else:
            # Try to find tesseract in PATH
            tesseract_path = shutil.which("tesseract")
            if tesseract_path:
                tesseract_found = True
                self.logger.info(f"Found tesseract in PATH at: {tesseract_path}")
            else:
                # Fallback: Check common installation paths (especially for macOS/Homebrew)
                # This helps when Streamlit runs with a different PATH than the terminal
                system = platform.system()
                common_paths = []
                
                if system == "Darwin":  # macOS
                    common_paths = [
                        "/usr/local/bin/tesseract",  # Homebrew (Intel)
                        "/opt/homebrew/bin/tesseract",  # Homebrew (Apple Silicon)
                        "/usr/bin/tesseract",  # System
                    ]
                elif system == "Linux":
                    common_paths = [
                        "/usr/bin/tesseract",  # Standard Linux location
                        "/usr/local/bin/tesseract",  # Custom install
                    ]
                elif system == "Windows":
                    common_paths = [
                        "C:\\Program Files\\Tesseract-OCR\\tesseract.exe",
                        "C:\\Program Files (x86)\\Tesseract-OCR\\tesseract.exe",
                    ]
                
                for path in common_paths:
                    if os.path.exists(path) and os.access(path, os.X_OK):
                        tesseract_path = path
                        tesseract_found = True
                        self.logger.info(f"Found tesseract at common path: {tesseract_path}")
                        break

        # Set the tesseract command path if found
        if tesseract_found and tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path

        # Verify tesseract is actually working
        if tesseract_found:
            try:
                # Test tesseract by getting version
                version = pytesseract.get_tesseract_version()
                self.logger.info(f"Tesseract verified and working (version: {version})")
            except Exception as e:
                self.logger.error(f"Tesseract found at {tesseract_path} but not working: {e}")
                self.logger.error(f"Error type: {type(e).__name__}")
                tesseract_found = False

        if not tesseract_found:
            system = platform.system()
            install_instructions = {
                "Darwin": "brew install tesseract",
                "Linux": "sudo apt-get install tesseract-ocr  # or: sudo yum install tesseract",
                "Windows": "Download from https://github.com/UB-Mannheim/tesseract/wiki",
            }
            install_cmd = install_instructions.get(system, "Install tesseract-ocr package")

            error_msg = (
                f"Tesseract OCR is not installed or not in PATH.\n\n"
                f"To install Tesseract:\n"
                f"  {system}: {install_cmd}\n\n"
                f"After installation, verify with: tesseract --version\n\n"
                f"Alternatively, set the path manually:\n"
                f"  - Set TESSERACT_CMD environment variable\n"
                f"  - Or pass tesseract_cmd parameter to OCRAttachmentParser()\n"
                f"  - Or add tesseract to your system PATH"
            )
            raise RuntimeError(error_msg)

        self.logger.info(f"Initialized OCR parser with model: {model}")

    def _is_pdf_attachment(self, attachment: Attachment) -> bool:
        """Check if attachment is a PDF file.

        Args:
            attachment: Attachment object

        Returns:
            True if PDF, False otherwise
        """
        filename_lower = attachment.filename.lower()
        return filename_lower.endswith(".pdf") or (
            attachment.content_type and "pdf" in attachment.content_type.lower()
        )

    def _is_image_attachment(self, attachment: Attachment) -> bool:
        """Check if attachment is an image file.

        Args:
            attachment: Attachment object

        Returns:
            True if image, False otherwise
        """
        filename_lower = attachment.filename.lower()
        image_extensions = [".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif"]
        return any(filename_lower.endswith(ext) for ext in image_extensions) or (
            attachment.content_type and "image" in attachment.content_type.lower()
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
            try:
                text = pytesseract.image_to_string(image)
            except pytesseract.TesseractNotFoundError:
                error_msg = (
                    "Tesseract OCR is not installed or not in PATH.\n\n"
                    "To install Tesseract:\n"
                    "  macOS: brew install tesseract\n"
                    "  Linux: sudo apt-get install tesseract-ocr\n"
                    "  Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki\n\n"
                    "After installation, verify with: tesseract --version\n\n"
                    "Alternatively, set the path manually:\n"
                    "  - Set TESSERACT_CMD environment variable\n"
                    "  - Or pass tesseract_cmd parameter to OCRAttachmentParser()"
                )
                raise RuntimeError(error_msg) from None

            # Extract bounding boxes with OCR data
            ocr_data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)

            bounding_boxes = []
            n_boxes = len(ocr_data["text"])

            for i in range(n_boxes):
                word = ocr_data["text"][i].strip()
                if word and int(ocr_data["conf"][i]) > 30:  # Confidence threshold
                    bbox = BoundingBox(
                        x=int(ocr_data["left"][i]),
                        y=int(ocr_data["top"][i]),
                        width=int(ocr_data["width"][i]),
                        height=int(ocr_data["height"][i]),
                        page=page_num,
                        confidence=float(ocr_data["conf"][i]) / 100.0,
                    )
                    bounding_boxes.append(bbox)

            self.logger.info(
                f"OCR extracted {len(text)} chars and {len(bounding_boxes)} boxes from page {page_num}"
            )
            return text, bounding_boxes

        except Exception as e:
            self.logger.error(f"OCR failed for page {page_num}: {e}")
            return "", []

    def _process_pdf_attachment(
        self, attachment: Attachment
    ) -> Tuple[str, Dict[str, List[BoundingBox]]]:
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

    def _process_image_attachment(
        self, attachment: Attachment
    ) -> Tuple[str, Dict[str, List[BoundingBox]]]:
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

    def _extract_with_llm(self, ocr_text: str, email_date: Optional[any] = None) -> Dict[str, Any]:
        """Use LLM to extract structured data from OCR text.

        Args:
            ocr_text: Text extracted via OCR
            email_date: Email date for temporal context

        Returns:
            Dict with extracted fields
        """
        from datetime import datetime

        email_year = email_date.year if email_date else datetime.now().year

        # Truncate if too long
        if len(ocr_text) > 10000:
            ocr_text = ocr_text[:10000] + "\n... [truncated]"

        prompt = f"""You are an expert at extracting structured information from investment teasers and pitch decks for a BC (British Columbia, Canada) focused private equity firm.

**CONTEXT:**
- Document is from {email_year}
- Firm prioritizes BC-based companies
- Need MOST RECENT EBITDA (TTM, LTM, or {email_year})

Extract the following fields from the OCR text below. Return ONLY a valid JSON object:

{{
  "hq_location": "string or null - Headquarters location",
  "ebitda_millions": number or null - EBITDA in millions,
  "company_name": "string or null - Company or project name",
  "sector": "string or null - Industry sector",
  "raw_ebitda_text": "string or null - Exact EBITDA text"
}}

**CRITICAL INSTRUCTIONS:**

FOR EBITDA:
- PRIORITIZE: TTM, LTM, or {email_year} EBITDA (not {email_year - 1})
- If multiple years shown, select MOST RECENT
- Look for: "Adjusted EBITDA", "Portfolio EBITDA", "LTM EBITDA"
- Convert to millions: $5.2M → 5.2, C$3.6M → 3.6

FOR LOCATIONS:
- PRIORITIZE BC cities: Vancouver, Victoria, Surrey, Burnaby, Richmond, Kelowna
- Look for: "HQ:", "Headquarters:", "Location:", "Based in"
- Include specific city and province if found

FOR COMPANY:
- Check document header/title
- Look for project code name or official company name

Return null for fields not found and ensure valid JSON format

OCR TEXT:
{ocr_text}

Return only the JSON object:"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a precise data extraction assistant. Return only valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=self.temperature,
                max_tokens=4096,
            )

            response_text = response.choices[0].message.content

            # Parse JSON
            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                response_text = response_text[start:end].strip()
            elif "```" in response_text:
                start = response_text.find("```") + 3
                end = response_text.find("```", start)
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
        original_sender = self.extract_original_sender(email_data)
        source_domain = self.extract_domain(original_sender) if original_sender else None
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
        extracted_data = self._extract_with_llm(combined_text, email_data.date)

        # Create opportunity
        opportunity = InvestmentOpportunity(
            source_domain=source_domain,
            recipient=recipient,
            hq_location=extracted_data.get("hq_location"),
            ebitda_millions=extracted_data.get("ebitda_millions"),
            date=email_data.date,
            company_name=extracted_data.get("company_name"),
            sector=extracted_data.get("sector"),
            raw_ebitda_text=extracted_data.get("raw_ebitda_text"),
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
