"""Base parser infrastructure and data models for email parsing.

This module provides the foundational classes and Pydantic models for
extracting investment opportunity data from .msg email files.
"""

import email
import email.utils
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import extract_msg
from pydantic import BaseModel, Field, field_validator

# Valid sector categories - must match exactly
VALID_SECTORS: Set[str] = {
    "Wholesale",
    "Transportation Services",
    "Transportation Products",
    "Retail",
    "Other",
    "Industrial Products",
    "Healthcare",
    "Electronics",
    "Consumer Services",
    "Business Services",
    "Building Products",
    "Agriculture / Forestry",
}

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
    description: Optional[str] = None  # Brief business description generated from email body
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

    def extract_eml_file(self, eml_path: Path) -> EmailData:
        """Extract data from a .eml email file.

        Args:
            eml_path: Path to the .eml file

        Returns:
            EmailData object with extracted email content

        Raises:
            FileNotFoundError: If eml_path doesn't exist
            Exception: If extraction fails
        """
        if not eml_path.exists():
            raise FileNotFoundError(f"Email file not found: {eml_path}")

        try:
            with open(eml_path, "rb") as f:
                msg = email.message_from_bytes(f.read())

            # Extract sender
            sender = msg.get("From", "")

            # Extract recipients
            recipients = []
            for header in ["To", "Cc", "Bcc"]:
                header_value = msg.get(header, "")
                if header_value:
                    # Parse email addresses from header
                    for addr in email.utils.getaddresses([header_value]):
                        if addr[1]:  # email address exists
                            recipients.append(addr[1])

            # Extract subject
            subject = msg.get("Subject", "")

            # Extract date
            date_str = msg.get("Date", "")
            date = None
            if date_str:
                try:
                    date = parsedate_to_datetime(date_str)
                except Exception:
                    self.logger.warning(f"Could not parse date: {date_str}")

            # Extract body (plain text and HTML)
            body_plain = None
            body_html = None

            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition", ""))

                    # Skip attachments
                    if "attachment" in content_disposition:
                        continue

                    # Get plain text body
                    if content_type == "text/plain" and body_plain is None:
                        try:
                            payload = part.get_payload(decode=True)
                            if payload:
                                body_plain = payload.decode("utf-8", errors="ignore")
                        except Exception as e:
                            self.logger.warning(f"Failed to decode plain text body: {e}")

                    # Get HTML body
                    if content_type == "text/html" and body_html is None:
                        try:
                            payload = part.get_payload(decode=True)
                            if payload:
                                body_html = payload.decode("utf-8", errors="ignore")
                        except Exception as e:
                            self.logger.warning(f"Failed to decode HTML body: {e}")
            else:
                # Single part message
                content_type = msg.get_content_type()
                payload = msg.get_payload(decode=True)
                if payload:
                    try:
                        decoded = payload.decode("utf-8", errors="ignore")
                        if content_type == "text/plain":
                            body_plain = decoded
                        elif content_type == "text/html":
                            body_html = decoded
                    except Exception as e:
                        self.logger.warning(f"Failed to decode body: {e}")

            email_data = EmailData(
                sender=sender,
                recipients=recipients,
                subject=subject,
                body_plain=body_plain,
                body_html=body_html,
                date=date,
            )

            # Extract attachments
            if msg.is_multipart():
                for part in msg.walk():
                    content_disposition = str(part.get("Content-Disposition", ""))
                    if "attachment" in content_disposition:
                        filename = part.get_filename()
                        if filename:
                            # Decode filename if it's encoded
                            try:
                                filename = email.utils.decode_rfc2231(filename) or filename
                            except Exception:
                                pass

                            payload = part.get_payload(decode=True)
                            if payload:
                                att = Attachment(
                                    filename=filename,
                                    content=payload,
                                    content_type=part.get_content_type(),
                                    size_bytes=len(payload),
                                )
                                email_data.attachments.append(att)

            self.logger.info(
                f"Extracted {len(email_data.attachments)} attachments from {eml_path.name}"
            )

            return email_data

        except Exception as e:
            self.logger.error(f"Failed to extract eml file {eml_path}: {e}")
            raise

    def extract_gmail_message(self, message: Dict[str, Any], gmail_service: Optional[Any] = None) -> EmailData:
        """Extract data from a Gmail API message object.

        Args:
            message: Gmail API message object (from messages.get with format='full')
            gmail_service: Optional Gmail API service object for downloading large attachments

        Returns:
            EmailData object with extracted email content

        Raises:
            Exception: If extraction fails
        """
        try:
            payload = message.get("payload", {})
            headers = payload.get("headers", [])
            message_id = message.get("id", "")

            # Extract headers
            header_dict = {h["name"].lower(): h["value"] for h in headers}

            sender = header_dict.get("from", "")
            subject = header_dict.get("subject", "")

            # Extract recipients
            recipients = []
            for header_name in ["to", "cc", "bcc"]:
                header_value = header_dict.get(header_name, "")
                if header_value:
                    for addr in email.utils.getaddresses([header_value]):
                        if addr[1]:  # email address exists
                            recipients.append(addr[1])

            # Extract date
            date_str = header_dict.get("date", "")
            date = None
            if date_str:
                try:
                    date = parsedate_to_datetime(date_str)
                except Exception:
                    self.logger.warning(f"Could not parse date: {date_str}")

            # Extract body and attachments
            body_plain = None
            body_html = None
            attachments = []

            def extract_parts(part: Dict[str, Any], part_id: str = "") -> None:
                """Recursively extract parts from multipart message."""
                nonlocal body_plain, body_html, attachments
                mime_type = part.get("mimeType", "")
                body_data = part.get("body", {})
                data = body_data.get("data", "")
                attachment_id = body_data.get("attachmentId")

                # Handle attachments
                filename = None
                for header in part.get("headers", []):
                    if header["name"].lower() == "content-disposition":
                        disposition = header["value"]
                        if "attachment" in disposition.lower():
                            # Extract filename
                            import re
                            filename_match = re.search(
                                r'filename[^;=\n]*=(([\'"]).*?\2|[^;\n]*)',
                                disposition,
                                re.IGNORECASE,
                            )
                            if filename_match:
                                filename = filename_match.group(1).strip('"\'')
                        break
                
                # Also check for filename in headers (some attachments don't have Content-Disposition)
                if not filename:
                    for header in part.get("headers", []):
                        if header["name"].lower() == "content-type":
                            # Try to extract filename from Content-Type header
                            content_type = header["value"]
                            import re
                            filename_match = re.search(r'name="?([^";]+)"?', content_type, re.IGNORECASE)
                            if filename_match:
                                filename = filename_match.group(1)
                        elif header["name"].lower() == "x-attachment-id" and part.get("filename"):
                            # Use filename from part if available
                            filename = part.get("filename")
                
                # Use part filename as fallback
                if not filename and part.get("filename"):
                    filename = part["filename"]

                # Handle attachment with inline data
                if filename and data:
                    # Decode base64 attachment
                    import base64
                    try:
                        attachment_content = base64.urlsafe_b64decode(data)
                        att = Attachment(
                            filename=filename,
                            content=attachment_content,
                            content_type=mime_type,
                            size_bytes=len(attachment_content),
                        )
                        attachments.append(att)
                    except Exception as e:
                        self.logger.warning(f"Failed to decode attachment {filename}: {e}")
                    return
                
                # Handle attachment with attachmentId (large attachments)
                if filename and attachment_id:
                    if gmail_service:
                        try:
                            import base64
                            # Download attachment using attachmentId
                            att_result = (
                                gmail_service.users()
                                .messages()
                                .attachments()
                                .get(userId="me", messageId=message_id, id=attachment_id)
                                .execute()
                            )
                            attachment_content = base64.urlsafe_b64decode(att_result["data"])
                            att = Attachment(
                                filename=filename,
                                content=attachment_content,
                                content_type=mime_type,
                                size_bytes=len(attachment_content),
                            )
                            attachments.append(att)
                            self.logger.debug(f"Downloaded attachment {filename} ({len(attachment_content)} bytes) using attachmentId")
                        except Exception as e:
                            self.logger.warning(f"Failed to download attachment {filename} using attachmentId: {e}")
                    else:
                        self.logger.warning(f"Attachment {filename} requires attachmentId download but gmail_service not provided")
                    return

                # Handle body content
                if data and not filename:
                    try:
                        import base64
                        decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

                        if mime_type == "text/plain" and body_plain is None:
                            body_plain = decoded
                        elif mime_type == "text/html" and body_html is None:
                            body_html = decoded
                    except Exception as e:
                        self.logger.warning(f"Failed to decode body part: {e}")

                # Recursively process sub-parts
                for idx, subpart in enumerate(part.get("parts", [])):
                    subpart_id = f"{part_id}/{idx}" if part_id else str(idx)
                    extract_parts(subpart, subpart_id)

            # Extract from payload
            extract_parts(payload, "0")

            # If no body found, try to get from payload body directly
            if not body_plain and not body_html:
                body_data = payload.get("body", {})
                data = body_data.get("data", "")
                if data:
                    try:
                        import base64
                        decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                        mime_type = payload.get("mimeType", "")
                        if mime_type == "text/html":
                            body_html = decoded
                        else:
                            body_plain = decoded
                    except Exception:
                        pass

            email_data = EmailData(
                sender=sender,
                recipients=recipients,
                subject=subject,
                body_plain=body_plain,
                body_html=body_html,
                date=date,
                attachments=attachments,
            )

            self.logger.info(
                f"Extracted {len(attachments)} attachments from Gmail message {message.get('id', 'unknown')}"
            )

            return email_data

        except Exception as e:
            self.logger.error(f"Failed to extract Gmail message: {e}")
            raise

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
            subject.upper().startswith("FW:")
            or subject.upper().startswith("FWD:")
            or "-----Original Message-----" in body
            or "---------- Forwarded message ----------" in body
        )

        if is_forward:
            # Try to find original "From:" line in body
            from_patterns = [
                r'From:\s*["\']?([^"\'\n<]+)<([^>]+)>',  # From: Name <email>
                r"From:\s*<?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>?",  # From: email
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

    def extract_original_recipient(self, email_data: EmailData) -> Optional[str]:
        """Extract original recipient from forwarded email.

        For forwarded emails, parses the body to find the original "To:" line.
        This represents who received the original email before it was forwarded.

        Args:
            email_data: Email data object

        Returns:
            Original recipient email address or None if not found
        """
        import re

        # Check if this is a forwarded email
        body = email_data.body_plain or ""
        subject = email_data.subject or ""

        # Look for forward indicators
        is_forward = (
            subject.upper().startswith("FW:")
            or subject.upper().startswith("FWD:")
            or "-----Original Message-----" in body
            or "---------- Forwarded message ----------" in body
        )

        if is_forward:
            # Try to find original "To:" line in body
            to_patterns = [
                r'To:\s*["\']?([^"\'\n<]+)<([^>]+)>',  # To: Name <email>
                r"To:\s*<?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>?",  # To: email
            ]

            for pattern in to_patterns:
                match = re.search(pattern, body, re.MULTILINE | re.IGNORECASE)
                if match:
                    # Extract email from match
                    if len(match.groups()) >= 2:
                        # Has name and email
                        original_email = match.group(2).strip()
                    else:
                        # Just email
                        original_email = match.group(1).strip()

                    if original_email and "@" in original_email:
                        self.logger.info(f"Found original recipient in forward: {original_email}")
                        return original_email

        return None

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
