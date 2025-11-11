"""Base parser infrastructure and data models for email parsing.

This module provides the foundational classes and Pydantic models for
extracting investment opportunity data from .msg email files.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import extract_msg
from pydantic import BaseModel, Field, field_validator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BoundingBox(BaseModel):
    """Represents a bounding box with pixel coordinates.

    Attributes:
        x: X-coordinate of top-left corner
        y: Y-coordinate of top-left corner
        width: Width of bounding box
        height: Height of bounding box
        page: Page number (for multi-page documents, 0-indexed)
        confidence: Optional confidence score (0.0 to 1.0)
    """

    x: int
    y: int
    width: int
    height: int
    page: int = 0
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)


class FieldOption(BaseModel):
    """A candidate value for a field with confidence score.

    Attributes:
        value: The extracted value
        confidence: Confidence score (0.0 to 1.0)
        source: Where this came from (e.g., "email body line 5", "PDF page 1")
        raw_text: Raw text that led to this extraction
    """

    value: Any
    confidence: float = Field(ge=0.0, le=1.0)
    source: str
    raw_text: Optional[str] = None


class InvestmentOpportunity(BaseModel):
    """Structured data for an investment opportunity.

    Attributes:
        source_domain: Email domain of sender (e.g., "kpmg.com")
        recipient: Krystal GP member who received the email
        hq_location: Headquarters location of the company
        ebitda_millions: EBITDA in millions of dollars
        date: Email timestamp
        bounding_boxes: Dict mapping field names to their bounding boxes
        company_name: Optional company or project name
        sector: Optional industry sector
        raw_ebitda_text: Raw text containing EBITDA mention

        # Multiple options with confidence scores
        ebitda_options: List of candidate EBITDA values with confidence
        location_options: List of candidate locations with confidence
        company_options: List of candidate company names with confidence
        sector_options: List of candidate sectors with confidence
    """

    source_domain: Optional[str] = None
    recipient: Optional[str] = None
    hq_location: Optional[str] = None
    ebitda_millions: Optional[float] = None
    date: Optional[datetime] = None
    bounding_boxes: Dict[str, List[BoundingBox]] = Field(default_factory=dict)

    # Additional fields for context
    company_name: Optional[str] = None
    sector: Optional[str] = None
    raw_ebitda_text: Optional[str] = None

    # Multiple options with confidence scores
    ebitda_options: List[FieldOption] = Field(default_factory=list)
    location_options: List[FieldOption] = Field(default_factory=list)
    company_options: List[FieldOption] = Field(default_factory=list)
    sector_options: List[FieldOption] = Field(default_factory=list)

    @field_validator("ebitda_millions")
    @classmethod
    def validate_ebitda(cls, v: Optional[float]) -> Optional[float]:
        """Validate EBITDA is non-negative if present."""
        if v is not None and v < 0:
            logger.warning(f"Negative EBITDA detected: {v}")
        return v


class ParserResult(BaseModel):
    """Result from a parser including extracted data and metadata.

    Attributes:
        opportunity: Extracted investment opportunity data
        parser_name: Name of the parser that extracted the data
        extraction_source: Where the data was extracted from (e.g., "body", "attachment")
        confidence: Overall confidence score (0.0 to 1.0)
        processing_time_seconds: Time taken to process
        raw_response: Optional raw response from the parser (e.g., LLM output)
        errors: List of errors encountered during parsing
    """

    opportunity: InvestmentOpportunity
    parser_name: str
    extraction_source: str  # "body", "attachment", "both"
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    processing_time_seconds: Optional[float] = None
    raw_response: Optional[Dict[str, Any]] = None
    errors: List[str] = Field(default_factory=list)


class Attachment(BaseModel):
    """Represents an email attachment.

    Attributes:
        filename: Name of the attachment file
        content: Binary content of the attachment
        content_type: MIME type
        size_bytes: Size in bytes
    """

    filename: str
    content: bytes
    content_type: Optional[str] = None
    size_bytes: int

    class Config:
        """Pydantic configuration."""

        arbitrary_types_allowed = True


class EmailData(BaseModel):
    """Parsed email data from .msg file.

    Attributes:
        sender: Email address of sender
        recipients: List of recipient email addresses
        subject: Email subject line
        body_plain: Plain text body
        body_html: HTML body
        date: Email timestamp
        attachments: List of attachments
    """

    sender: Optional[str] = None
    recipients: List[str] = Field(default_factory=list)
    subject: Optional[str] = None
    body_plain: Optional[str] = None
    body_html: Optional[str] = None
    date: Optional[datetime] = None
    attachments: List[Attachment] = Field(default_factory=list)


class BaseParser(ABC):
    """Abstract base class for all email parsers.

    All parser implementations should inherit from this class and implement
    the parse_data method.
    """

    def __init__(self, name: str):
        """Initialize base parser.

        Args:
            name: Name of the parser for identification
        """
        self.name = name
        self.logger = logging.getLogger(f"{__name__}.{name}")

    def extract_msg_file(self, msg_path: Path) -> EmailData:
        """Extract data from a .msg email file.

        Args:
            msg_path: Path to the .msg file

        Returns:
            EmailData object with extracted email content

        Raises:
            FileNotFoundError: If msg_path doesn't exist
            Exception: If extraction fails
        """
        if not msg_path.exists():
            raise FileNotFoundError(f"Email file not found: {msg_path}")

        try:
            msg = extract_msg.Message(msg_path)

            # Extract basic email data
            # Handle both string and bytes for body content
            body_plain = msg.body
            if isinstance(body_plain, bytes):
                try:
                    body_plain = body_plain.decode("utf-8", errors="ignore")
                except Exception:
                    body_plain = str(body_plain)

            body_html = getattr(msg, "htmlBody", None)
            if isinstance(body_html, bytes):
                try:
                    body_html = body_html.decode("utf-8", errors="ignore")
                except Exception:
                    body_html = str(body_html)

            email_data = EmailData(
                sender=msg.sender,
                recipients=self._extract_recipients(msg),
                subject=msg.subject,
                body_plain=body_plain,
                body_html=body_html,
                date=msg.date,
            )

            # Extract attachments
            for attachment in msg.attachments:
                if hasattr(attachment, "data"):
                    att = Attachment(
                        filename=attachment.longFilename or attachment.shortFilename,
                        content=attachment.data,
                        content_type=attachment.mimetype,
                        size_bytes=len(attachment.data) if attachment.data else 0,
                    )
                    email_data.attachments.append(att)

            msg.close()
            self.logger.info(
                f"Extracted {len(email_data.attachments)} attachments from {msg_path.name}"
            )

            return email_data

        except Exception as e:
            self.logger.error(f"Failed to extract msg file {msg_path}: {e}")
            raise

    def _extract_recipients(self, msg: extract_msg.Message) -> List[str]:
        """Extract recipient email addresses from message.

        Args:
            msg: extract_msg Message object

        Returns:
            List of recipient email addresses
        """
        recipients = []

        # Try to get recipients from TO field
        if msg.to:
            recipients.extend([r.strip() for r in msg.to.split(";") if r.strip()])

        # Try to get recipients from CC field
        if msg.cc:
            recipients.extend([r.strip() for r in msg.cc.split(";") if r.strip()])

        return recipients

    def extract_original_sender(self, email_data: EmailData) -> Optional[str]:
        """Extract original sender from forwarded email.
        
        For forwarded emails, parses the body to find the original "From:" line.
        Falls back to immediate sender if not a forward.
        
        Args:
            email_data: Email data object
            
        Returns:
            Original sender email address or immediate sender
        """
        import re
        
        # Check if this is a forwarded email
        body = email_data.body_plain or ""
        subject = email_data.subject or ""
        
        # Look for forward indicators
        is_forward = (
            subject.upper().startswith("FW:") or 
            subject.upper().startswith("FWD:") or
            "-----Original Message-----" in body or
            "---------- Forwarded message ----------" in body
        )
        
        if is_forward:
            # Try to find original "From:" line in body
            from_patterns = [
                r'From:\s*["\']?([^"\'\n<]+)<([^>]+)>',  # From: Name <email>
                r'From:\s*<?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>?',  # From: email
            ]
            
            for pattern in from_patterns:
                match = re.search(pattern, body, re.MULTILINE | re.IGNORECASE)
                if match:
                    # Extract email from match
                    if len(match.groups()) >= 2:
                        # Has name and email
                        original_email = match.group(2).strip()
                    else:
                        # Just email
                        original_email = match.group(1).strip()
                    
                    # Validate it's not a Krystal GP email
                    if original_email and "@" in original_email:
                        domain = original_email.split("@")[1].lower()
                        if "krystal" not in domain:
                            self.logger.info(f"Found original sender in forward: {original_email}")
                            return original_email
        
        # Fall back to immediate sender
        return email_data.sender

    def extract_domain(self, email: str) -> Optional[str]:
        """Extract domain from email address.

        Args:
            email: Email address

        Returns:
            Domain name or None if extraction fails

        Examples:
            >>> parser.extract_domain("john@kpmg.com")
            "kpmg.com"
        """
        if not email:
            return None

        try:
            # Handle email addresses with display names like "John Doe <john@kpmg.com>"
            if "<" in email and ">" in email:
                email = email.split("<")[1].split(">")[0]

            parts = email.split("@")
            if len(parts) == 2:
                return parts[1].strip().lower()
        except Exception as e:
            self.logger.warning(f"Failed to extract domain from '{email}': {e}")

        return None

    @abstractmethod
    def parse_data(self, email_data: EmailData) -> InvestmentOpportunity:
        """Parse email data and extract investment opportunity information.

        This method must be implemented by all concrete parser classes.

        Args:
            email_data: Extracted email data

        Returns:
            InvestmentOpportunity with extracted fields
        """
        pass

    def parse(self, msg_path: Path) -> ParserResult:
        """Parse a .msg file and extract investment opportunity data.

        This is the main entry point for using a parser.

        Args:
            msg_path: Path to the .msg file

        Returns:
            ParserResult with extracted data and metadata
        """
        start_time = datetime.now()
        errors = []

        try:
            # Extract email data
            email_data = self.extract_msg_file(msg_path)

            # Parse the data
            opportunity = self.parse_data(email_data)

            # Calculate processing time
            processing_time = (datetime.now() - start_time).total_seconds()

            return ParserResult(
                opportunity=opportunity,
                parser_name=self.name,
                extraction_source="unknown",  # Subclasses should set this
                processing_time_seconds=processing_time,
                errors=errors,
            )

        except Exception as e:
            self.logger.error(f"Parsing failed for {msg_path}: {e}")
            errors.append(str(e))

            # Return empty result with error
            processing_time = (datetime.now() - start_time).total_seconds()
            return ParserResult(
                opportunity=InvestmentOpportunity(),
                parser_name=self.name,
                extraction_source="error",
                processing_time_seconds=processing_time,
                errors=errors,
            )
