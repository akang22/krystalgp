"""Script to parse emails from Gmail and update Google Sheets.

This script:
1. Searches Gmail for emails from specific domains/addresses
2. Filters out already-parsed emails using Gmail labels
3. Parses emails using LLM Body, OCR+LLM, and Layout Vision parsers
4. Updates Google Sheet with results matching Streamlit summary table format
"""

import base64
import email.utils
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from functools import wraps

from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from email_parser.base import BaseParser, EmailData
from email_parser.ensemble_parser import EnsembleParser
from email_parser.layout_attachment_parser import LayoutLLMParser
from email_parser.llm_body_parser import LLMBodyParser
from email_parser.ocr_attachment_parser import OCRAttachmentParser

# Load environment variables
load_dotenv()

# Configure logging
log_dir = Path(__file__).parent.parent / "logs"
log_dir.mkdir(exist_ok=True)
log_file = log_dir / f"gmail_parser_methods_{time.strftime('%Y%m%d')}.log"

# Create formatter
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

# File handler for detailed method tracking
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)

# Configure root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)
logger.info(f"Logging to file: {log_file}")

# Google API imports
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError as e:
    logger.error(
        f"Google API libraries not installed. Run: uv pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
    )
    sys.exit(1)


def retry_on_rate_limit(max_retries: int = 3, delay: int = 5):
    """Decorator to retry API calls on rate limit errors.

    Args:
        max_retries: Maximum number of retries
        delay: Delay in seconds between retries
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except HttpError as error:
                    if error.resp.status == 429:  # Rate limit
                        if attempt < max_retries - 1:
                            wait_time = delay * (attempt + 1)
                            logger.warning(
                                f"Rate limit hit, waiting {wait_time}s before retry {attempt + 1}/{max_retries}"
                            )
                            time.sleep(wait_time)
                            continue
                        else:
                            logger.error(f"Rate limit exceeded after {max_retries} retries")
                            raise
                    else:
                        raise
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Error in {func.__name__}, retrying: {e}")
                        time.sleep(delay)
                        continue
                    else:
                        raise
            return None
        return wrapper
    return decorator

# Gmail API scopes
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",  # For labels
    "https://www.googleapis.com/auth/spreadsheets",  # For Sheets
]


def authenticate_gmail() -> Any:
    """Authenticate and return Gmail service.

    Returns:
        Gmail API service object

    Raises:
        Exception: If authentication fails
    """
    creds = None
    token_path = os.getenv("GMAIL_TOKEN_PATH", "token.json")
    credentials_path = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")

    # Load existing token
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    # If no valid credentials, get new ones
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                logger.error(
                    f"Credentials file not found: {credentials_path}. "
                    "Set GMAIL_CREDENTIALS_PATH environment variable or place credentials.json in current directory."
                )
                raise FileNotFoundError(f"Credentials file not found: {credentials_path}")

            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save credentials for next run
        with open(token_path, "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def authenticate_sheets() -> Any:
    """Authenticate and return Google Sheets service.

    Uses same credentials as Gmail (shared token).

    Returns:
        Google Sheets API service object

    Raises:
        Exception: If authentication fails
    """
    creds = None
    token_path = os.getenv("GMAIL_TOKEN_PATH", "token.json")
    credentials_path = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")

    # Load existing token
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    # If no valid credentials, get new ones
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                logger.error(
                    f"Credentials file not found: {credentials_path}. "
                    "Set GMAIL_CREDENTIALS_PATH environment variable or place credentials.json in current directory."
                )
                raise FileNotFoundError(f"Credentials file not found: {credentials_path}")

            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save credentials for next run
        with open(token_path, "w") as token:
            token.write(creds.to_json())

    return build("sheets", "v4", credentials=creds)


def get_or_create_label(gmail_service: Any, label_name: str) -> str:
    """Get existing label or create it if it doesn't exist.

    Args:
        gmail_service: Gmail API service object
        label_name: Name of the label

    Returns:
        Label ID
    """
    try:
        # List all labels
        results = gmail_service.users().labels().list(userId="me").execute()
        labels = results.get("labels", [])

        # Check if label exists
        for label in labels:
            if label["name"] == label_name:
                logger.info(f"Found existing label: {label_name} (ID: {label['id']})")
                return label["id"]

        # Create label if it doesn't exist
        logger.info(f"Creating new label: {label_name}")
        label_obj = {"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
        created = gmail_service.users().labels().create(userId="me", body=label_obj).execute()
        logger.info(f"Created label: {label_name} (ID: {created['id']})")
        return created["id"]

    except HttpError as error:
        logger.error(f"Error managing label: {error}")
        raise


@retry_on_rate_limit(max_retries=3, delay=5)
def build_gmail_search_query(
    search_patterns: str, parsed_label_name: Optional[str] = None, recipient_filter: Optional[str] = None
) -> str:
    """Build Gmail search query from search patterns.

    Supports:
    - Exact email: "user@example.com"
    - Domain: "example.com" or "*@example.com"
    - Multiple patterns: comma or space separated

    Args:
        search_patterns: Comma or space separated list of email/domain patterns
        parsed_label_name: Label name to exclude (already parsed emails)
        recipient_filter: Recipient email address to filter by (e.g., "hello+krystalgptestinbox@photoncollective.dev")

    Returns:
        Gmail search query string
    """
    # Split by comma or space
    patterns = [p.strip() for p in search_patterns.replace(",", " ").split() if p.strip()]
    
    if not patterns:
        raise ValueError("No search patterns provided")
    
    # Build from: conditions
    from_conditions = []
    for pattern in patterns:
        # Handle wildcard pattern *@domain.com -> domain.com
        if pattern.startswith("*@"):
            domain = pattern[2:]  # Remove "*@"
            from_conditions.append(f"from:{domain}")
        # Handle exact email (contains @ but not at start)
        elif "@" in pattern and not pattern.startswith("*"):
            from_conditions.append(f'from:"{pattern}"')  # Quote for exact match
        # Handle domain (no @)
        else:
            from_conditions.append(f"from:{pattern}")
    
    # Combine with OR
    if len(from_conditions) == 1:
        query = from_conditions[0]
    else:
        # Gmail uses OR implicitly with space, but we can be explicit
        from_part = " OR ".join(from_conditions)
        query = f"({from_part})"
    
    # Add recipient filter if provided
    if recipient_filter:
        query += f' to:"{recipient_filter}"'
    
    # Exclude already parsed emails (use label name, not ID, for Gmail search)
    if parsed_label_name:
        # Escape spaces in label name if needed
        label_query = parsed_label_name.replace(" ", "_")
        query += f' -label:{label_query}'
    
    return query


def search_gmail_forwards(
    gmail_service: Any,
    search_patterns: str,
    parsed_label_name: Optional[str] = None,
    recipient_filter: Optional[str] = None,
    max_results: int = 50,
) -> List[Dict[str, Any]]:
    """Search Gmail for emails matching search patterns.

    Args:
        gmail_service: Gmail API service object
        search_patterns: Comma or space separated list of email/domain patterns
            Examples: "kpmg.com", "*@krystalgp.com", "user@example.com", "kpmg.com *@krystalgp.com"
        parsed_label_name: Label name to exclude (already parsed emails)
        recipient_filter: Recipient email address to filter by (e.g., "hello+krystalgptestinbox@photoncollective.dev")
        max_results: Maximum number of results to return

    Returns:
        List of message objects
    """
    # Build search query
    query = build_gmail_search_query(search_patterns, parsed_label_name, recipient_filter)

    logger.info(f"Searching Gmail with query: {query}")

    try:
        # Search for messages
        results = (
            gmail_service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        messages = results.get("messages", [])

        logger.info(f"Found {len(messages)} messages matching query")

        return messages

    except HttpError as error:
        logger.error(f"Error searching Gmail: {error}")
        raise


@retry_on_rate_limit(max_retries=3, delay=5)
def get_message_details(gmail_service: Any, message_id: str) -> Dict[str, Any]:
    """Get full message details from Gmail.

    Args:
        gmail_service: Gmail API service object
        message_id: Gmail message ID

    Returns:
        Full message object
    """
    try:
        message = (
            gmail_service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        return message
    except HttpError as error:
        logger.error(f"Error getting message {message_id}: {error}")
        raise


def add_label_to_message(gmail_service: Any, message_id: str, label_id: str) -> None:
    """Add a label to a Gmail message.

    Args:
        gmail_service: Gmail API service object
        message_id: Gmail message ID
        label_id: Label ID to add
    """
    try:
        result = gmail_service.users().messages().modify(
            userId="me", id=message_id, body={"addLabelIds": [label_id]}
        ).execute()
        # Verify label was added
        label_ids = result.get("labelIds", [])
        if label_id in label_ids:
            logger.info(f"✓ Added label to message {message_id}")
        else:
            logger.warning(f"Label may not have been added to message {message_id}. Label IDs: {label_ids}")
    except HttpError as error:
        logger.error(f"Error adding label to message {message_id}: {error}")
        raise


@retry_on_rate_limit(max_retries=3, delay=5)
def mark_as_read_and_archive(gmail_service: Any, message_id: str) -> None:
    """Mark a Gmail message as read and archive it.

    Args:
        gmail_service: Gmail API service object
        message_id: Gmail message ID
    """
    try:
        # Get INBOX label ID
        labels = gmail_service.users().labels().list(userId="me").execute()
        inbox_label_id = None
        for label in labels.get("labels", []):
            if label["name"] == "INBOX":
                inbox_label_id = label["id"]
                break

        # Remove INBOX label (archives) and remove UNREAD label (marks as read)
        modify_body = {"removeLabelIds": ["UNREAD"]}
        if inbox_label_id:
            modify_body["removeLabelIds"].append(inbox_label_id)

        result = gmail_service.users().messages().modify(
            userId="me", id=message_id, body=modify_body
        ).execute()

        logger.info(f"✓ Marked as read and archived message {message_id}")
    except HttpError as error:
        logger.error(f"Error marking as read/archiving message {message_id}: {error}")
        raise


def calculate_investment_criteria_fit(hq_location: Optional[str], ebitda_millions: Optional[float]) -> str:
    """Calculate if investment opportunity fits criteria.

    Criteria: HQ = Western Canada (BC or Alberta) && EBITDA between 2-8M

    Args:
        hq_location: Headquarters location
        ebitda_millions: EBITDA in millions

    Returns:
        "Yes" if criteria met, "No" otherwise
    """
    if not hq_location or ebitda_millions is None:
        return "No"

    location_upper = hq_location.upper()

    # Check for province abbreviations/names
    is_western_canada = (
        "BC" in location_upper
        or "BRITISH COLUMBIA" in location_upper
        or "ALBERTA" in location_upper
        or "AB" in location_upper
    )

    # Check for regional terms
    if not is_western_canada:
        western_terms = [
            "WEST COAST",
            "WESTERN CANADA",
            "WESTERN CANADIAN",
            "BC-BASED",
            "ALBERTA-BASED",
            "PACIFIC COAST",
        ]
        for term in western_terms:
            if term in location_upper:
                is_western_canada = True
                break

    # Check for major cities
    if not is_western_canada:
        western_canada_cities = [
            "VANCOUVER",
            "VICTORIA",
            "SURREY",
            "BURNABY",
            "RICHMOND",
            "COQUITLAM",
            "LANGLEY",
            "ABBOTSFORD",
            "NORTH VANCOUVER",
            "WEST VANCOUVER",
            "KELOWNA",
            "KAMLOOPS",
            "NANAIMO",
            "PRINCE GEORGE",
            "CHILLIWACK",
            "CALGARY",
            "EDMONTON",
            "RED DEER",
            "LETHBRIDGE",
            "ST. ALBERT",
            "MEDICINE HAT",
            "GRANDE PRAIRIE",
            "AIRDRIE",
            "SPRUCE GROVE",
            "FORT MCMURRAY",
        ]
        for city in western_canada_cities:
            if city in location_upper:
                is_western_canada = True
                break

    # Check if EBITDA is between 2-8M
    ebitda_in_range = 2.0 <= ebitda_millions <= 8.0

    return "Yes" if (is_western_canada and ebitda_in_range) else "No"


def format_row_for_sheet(
    email_data: EmailData, opportunity: Any, llm_body_result: Optional[Any] = None, extractor_parser: Optional[Any] = None
) -> List[str]:
    """Format parser results for Google Sheet row.

    Args:
        email_data: EmailData object
        opportunity: InvestmentOpportunity from ensemble parser
        llm_body_result: Optional LLM Body parser result for description
        extractor_parser: Parser instance to extract original recipient (optional)

    Returns:
        List of values for the row
    """
    # Date Received
    date_received = email_data.date.strftime("%Y-%m-%d") if email_data.date else "N/A"

    # Company / Project Name
    company_name = opportunity.company_name or "N/A"

    # Sector
    sector = opportunity.sector or "N/A"

    # Description (prefer LLM-generated, fallback to subject)
    description = "N/A"
    if llm_body_result and llm_body_result.opportunity:
        llm_opp = llm_body_result.opportunity
        if hasattr(llm_opp, "description") and llm_opp.description:
            description = llm_opp.description
    if description == "N/A":
        description = email_data.subject or "N/A"

    # LTM EBITDA ($M)
    if opportunity.ebitda_millions is not None:
        ebitda = f"${opportunity.ebitda_millions:.2f}M"
    else:
        ebitda = "N/A (undetermined)"

    # HQ Location - check confidence threshold
    # If location has low confidence (< 0.75) or no location options, mark as undetermined
    LOCATION_CONFIDENCE_THRESHOLD = 0.75
    hq_location = "N/A (undetermined)"
    if opportunity.hq_location:
        # Check if we have location options with confidence scores
        if opportunity.location_options:
            # Find the location option that matches the selected hq_location
            matching_option = None
            for loc_opt in opportunity.location_options:
                if loc_opt.value == opportunity.hq_location:
                    matching_option = loc_opt
                    break
            
            # If we found a matching option, check its confidence
            if matching_option:
                # Use location if confidence >= threshold, otherwise mark as undetermined
                if matching_option.confidence >= LOCATION_CONFIDENCE_THRESHOLD:
                    hq_location = opportunity.hq_location
                # else: already set to "N/A (undetermined)" - low confidence
            else:
                # Location exists but no matching option found
                # This can happen when location comes from a fallback source (e.g., Vision parser)
                # If location was extracted from attachment (more reliable), use it
                # Otherwise mark as undetermined
                # Check if this came from attachment-based parser by checking extraction_source
                # Since we don't have direct access, we'll be conservative and use it
                # if it's a reasonable location (not just "Canada" or too generic)
                location_value = opportunity.hq_location
                # Generic locations that might be unreliable
                generic_locations = ["Canada", "North America", "United States", "US", "USA"]
                if location_value not in generic_locations:
                    # More specific location - likely reliable even without confidence score
                    hq_location = opportunity.hq_location
                else:
                    # Generic location without confidence - mark as undetermined
                    hq_location = "N/A (undetermined)"
        else:
            # No location options available
            # If location was extracted, it likely came from a fallback source
            # Use it if it's specific enough, otherwise mark as undetermined
            location_value = opportunity.hq_location
            generic_locations = ["Canada", "North America", "United States", "US", "USA"]
            if location_value and location_value not in generic_locations:
                # Specific location (e.g., "Western Canada", "Vancouver, BC") - use it
                hq_location = opportunity.hq_location
            else:
                # Generic or missing location - mark as undetermined
                hq_location = "N/A (undetermined)"

    # Source
    source = opportunity.source_domain or "N/A"

    # Receiver (extract username from original recipient email in forwarded message)
    receiver = "N/A"
    # Try to extract original recipient from forwarded email
    original_recipient = None
    if extractor_parser and hasattr(extractor_parser, 'extract_original_recipient'):
        original_recipient = extractor_parser.extract_original_recipient(email_data)
    
    # Use original recipient if found, otherwise fall back to opportunity.recipient
    recipient_email = original_recipient or opportunity.recipient or (email_data.recipients[0] if email_data.recipients else None)
    if recipient_email:
        parsed_addr = email.utils.parseaddr(recipient_email)
        email_addr = parsed_addr[1] if parsed_addr[1] else recipient_email
        if "@" in email_addr:
            receiver = email_addr.split("@")[0]
        else:
            receiver = email_addr

    # Investment Criteria Fit?
    investment_fit = calculate_investment_criteria_fit(opportunity.hq_location, opportunity.ebitda_millions)

    return [
        date_received,
        company_name,
        sector,
        description,
        ebitda,
        hq_location,
        source,
        receiver,
        investment_fit,
    ]


@retry_on_rate_limit(max_retries=3, delay=5)
def append_to_sheet(sheets_service: Any, spreadsheet_id: str, sheet_name: str, row: List[str]) -> None:
    """Append a row to Google Sheet.

    Args:
        sheets_service: Google Sheets API service object
        spreadsheet_id: Google Sheet ID
        sheet_name: Worksheet name
        row: List of values for the row
    """
    try:
        # Ensure headers exist
        range_name = f"{sheet_name}!A1:I1"
        headers = [
            "Date Received",
            "Company / Project Name",
            "Sector",
            "Description",
            "LTM EBITDA ($M)",
            "HQ Location",
            "Source",
            "Receiver",
            "Investment Criteria Fit?",
        ]

        # Check if headers exist
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=range_name
        ).execute()
        existing_headers = result.get("values", [])

        if not existing_headers:
            # Add headers
            sheets_service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption="RAW",
                body={"values": [headers]},
            ).execute()
            logger.info("Added headers to sheet")

        # Append row
        append_range = f"{sheet_name}!A:I"
        sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=append_range,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()

        logger.info(f"Appended row to sheet: {row[1]}")  # Log company name

    except HttpError as error:
        logger.error(f"Error appending to sheet: {error}")
        raise


def main():
    """Main function to parse Gmail forwards and update Google Sheet."""
    logger.info("=" * 80)
    logger.info("Gmail Forward Parser - Starting")
    logger.info("=" * 80)

    # Load configuration
    search_patterns = os.getenv("GMAIL_SEARCH_DOMAIN") or os.getenv("GMAIL_SEARCH_PATTERNS")
    if not search_patterns:
        logger.error(
            "GMAIL_SEARCH_DOMAIN or GMAIL_SEARCH_PATTERNS environment variable not set. "
            "Examples: 'kpmg.com', '*@krystalgp.com', 'user@example.com', 'kpmg.com *@krystalgp.com'"
        )
        sys.exit(1)

    parsed_label_name = os.getenv("GMAIL_PARSED_LABEL", "ParsedByEmailParser")
    recipient_filter = os.getenv("GMAIL_RECIPIENT_FILTER")  # e.g., "hello+krystalgptestinbox@photoncollective.dev"
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not sheet_id:
        logger.error("GOOGLE_SHEET_ID environment variable not set")
        sys.exit(1)

    # Extract sheet ID from URL if full URL provided
    if "/spreadsheets/d/" in sheet_id:
        sheet_id = sheet_id.split("/spreadsheets/d/")[1].split("/")[0]

    sheet_name = os.getenv("GOOGLE_SHEET_NAME", "Sheet1")
    max_emails = int(os.getenv("GMAIL_MAX_EMAILS", "50"))

    logger.info(f"Configuration:")
    logger.info(f"  Search Patterns: {search_patterns}")
    logger.info(f"  Recipient Filter: {recipient_filter or 'None (all recipients)'}")
    logger.info(f"  Parsed Label: {parsed_label_name}")
    logger.info(f"  Sheet ID: {sheet_id}")
    logger.info(f"  Sheet Name: {sheet_name}")
    logger.info(f"  Max Emails: {max_emails}")

    # Authenticate
    logger.info("\nAuthenticating with Gmail API...")
    gmail_service = authenticate_gmail()

    logger.info("Authenticating with Google Sheets API...")
    sheets_service = authenticate_sheets()

    # Get or create parsed label
    logger.info(f"\nManaging label: {parsed_label_name}")
    parsed_label_id = get_or_create_label(gmail_service, parsed_label_name)

    # Search for emails
    logger.info(f"\nSearching for emails matching: {search_patterns}...")
    messages = search_gmail_forwards(gmail_service, search_patterns, parsed_label_name, recipient_filter, max_emails)

    if not messages:
        logger.info("No new emails to process")
        return

    logger.info(f"Found {len(messages)} emails to process")

    # Initialize parsers
    logger.info("\nInitializing parsers...")
    parsers = {}
    parser_status = {}
    
    try:
        parsers["LLM Body"] = LLMBodyParser()
        parser_status["LLM Body"] = {"status": "initialized", "model": "gpt-4-turbo-preview"}
        logger.info("  ✓ LLM Body Parser initialized")
    except Exception as e:
        parser_status["LLM Body"] = {"status": "failed", "error": str(e)}
        logger.warning(f"  ✗ LLM Body Parser: {e}")

    try:
        parsers["OCR + LLM"] = OCRAttachmentParser()
        parser_status["OCR + LLM"] = {"status": "initialized", "model": "gpt-4-turbo-preview"}
        logger.info("  ✓ OCR + LLM Parser initialized")
    except Exception as e:
        parser_status["OCR + LLM"] = {"status": "failed", "error": str(e)}
        logger.warning(f"  ✗ OCR + LLM Parser: {e}")

    try:
        parsers["Layout Vision"] = LayoutLLMParser()
        parser_status["Layout Vision"] = {"status": "initialized", "model": "gpt-4o"}
        logger.info("  ✓ Layout Vision Parser initialized")
    except Exception as e:
        parser_status["Layout Vision"] = {"status": "failed", "error": str(e)}
        logger.warning(f"  ✗ Layout Vision Parser: {e}")

    try:
        parsers["Final Results"] = EnsembleParser(use_llm=True, use_vision=True, use_ocr=False)
        parser_status["Final Results"] = {"status": "initialized", "components": ["LLM", "Vision"]}
        logger.info("  ✓ Ensemble Parser initialized")
    except Exception as e:
        parser_status["Final Results"] = {"status": "failed", "error": str(e)}
        logger.warning(f"  ✗ Ensemble Parser: {e}")

    if not parsers:
        logger.error("No parsers available. Check your configuration.")
        sys.exit(1)

    # Log parser initialization summary
    logger.info("\n=== Parser Initialization Summary ===")
    for parser_name, status in parser_status.items():
        logger.info(f"  {parser_name}: {status['status']}")
        if status['status'] == 'initialized' and 'model' in status:
            logger.info(f"    Model: {status['model']}")
        elif status['status'] == 'failed':
            logger.info(f"    Error: {status['error']}")
    logger.info("=" * 40)

    # Use any available parser for email extraction (all inherit from BaseParser)
    extractor_parser = list(parsers.values())[0]
    logger.info(f"Using {extractor_parser.name} for email extraction")

    # Process each email
    logger.info(f"\nProcessing {len(messages)} emails...")
    processed_count = 0
    error_count = 0

    for idx, msg in enumerate(messages, 1):
        message_id = msg["id"]
        logger.info(f"\n[{idx}/{len(messages)}] Processing message {message_id}...")

        try:
            # Get full message
            full_message = get_message_details(gmail_service, message_id)

            # Extract email data from Gmail message (pass gmail_service for large attachments)
            email_data = extractor_parser.extract_gmail_message(full_message, gmail_service=gmail_service)

            logger.info(f"  Subject: {email_data.subject}")
            logger.info(f"  From: {email_data.sender}")
            logger.info(f"  Attachments: {len(email_data.attachments)}")

            # Run parsers
            results = {}
            llm_body_result = None
            parser_execution_log = {}

            logger.info("  === Running Parsers ===")
            for parser_name, parser in parsers.items():
                parser_start_time = time.time()
                parser_execution_log[parser_name] = {
                    "start_time": parser_start_time,
                    "status": "running",
                    "method": "parse_data",
                }
                
                if parser_name == "Final Results":
                    # Ensemble parser uses parse_data directly
                    try:
                        opportunity = parser.parse_data(email_data)
                        parser_end_time = time.time()
                        processing_time = parser_end_time - parser_start_time
                        
                        results[parser_name] = opportunity
                        parser_execution_log[parser_name].update({
                            "status": "success",
                            "processing_time": processing_time,
                            "ebitda": opportunity.ebitda_millions,
                            "company": opportunity.company_name,
                            "location": opportunity.hq_location,
                            "sector": opportunity.sector,
                        })
                        
                        logger.info(
                            f"  ✓ {parser_name}: EBITDA=${opportunity.ebitda_millions}M"
                            if opportunity.ebitda_millions
                            else f"  ✓ {parser_name}: No EBITDA"
                        )
                        logger.info(f"    Processing time: {processing_time:.2f}s")
                        logger.info(f"    Company: {opportunity.company_name or 'N/A'}")
                        logger.info(f"    Location: {opportunity.hq_location or 'N/A'}")
                        logger.info(f"    Sector: {opportunity.sector or 'N/A'}")
                    except Exception as e:
                        parser_end_time = time.time()
                        processing_time = parser_end_time - parser_start_time
                        parser_execution_log[parser_name].update({
                            "status": "failed",
                            "processing_time": processing_time,
                            "error": str(e),
                        })
                        logger.error(f"  ✗ {parser_name} failed: {e}")
                        logger.error(f"    Processing time: {processing_time:.2f}s")
                        results[parser_name] = None
                else:
                    # Other parsers use parse_data
                    try:
                        opportunity = parser.parse_data(email_data)
                        parser_end_time = time.time()
                        processing_time = parser_end_time - parser_start_time
                        
                        results[parser_name] = opportunity
                        parser_execution_log[parser_name].update({
                            "status": "success",
                            "processing_time": processing_time,
                            "ebitda": opportunity.ebitda_millions,
                            "company": opportunity.company_name,
                            "location": opportunity.hq_location,
                            "sector": opportunity.sector,
                        })
                        
                        if parser_name == "LLM Body":
                            # Store the opportunity for description extraction
                            from email_parser.base import ParserResult
                            llm_body_result = ParserResult(
                                opportunity=opportunity,
                                parser_name="LLM Body",
                                extraction_source="body",
                            )
                        
                        logger.info(
                            f"  ✓ {parser_name}: EBITDA=${opportunity.ebitda_millions}M"
                            if opportunity.ebitda_millions
                            else f"  ✓ {parser_name}: No EBITDA"
                        )
                        logger.info(f"    Processing time: {processing_time:.2f}s")
                        logger.info(f"    Company: {opportunity.company_name or 'N/A'}")
                        logger.info(f"    Location: {opportunity.hq_location or 'N/A'}")
                        logger.info(f"    Sector: {opportunity.sector or 'N/A'}")
                    except Exception as e:
                        parser_end_time = time.time()
                        processing_time = parser_end_time - parser_start_time
                        parser_execution_log[parser_name].update({
                            "status": "failed",
                            "processing_time": processing_time,
                            "error": str(e),
                        })
                        logger.error(f"  ✗ {parser_name} failed: {e}")
                        logger.error(f"    Processing time: {processing_time:.2f}s")
                        results[parser_name] = None
            
            # Log parser execution summary
            logger.info("  === Parser Execution Summary ===")
            for parser_name, log_entry in parser_execution_log.items():
                logger.info(f"  {parser_name}:")
                logger.info(f"    Status: {log_entry['status']}")
                logger.info(f"    Method: {log_entry['method']}")
                logger.info(f"    Time: {log_entry.get('processing_time', 0):.2f}s")
                if log_entry['status'] == 'success':
                    logger.info(f"    EBITDA: ${log_entry.get('ebitda') or 'N/A'}M")
                    logger.info(f"    Company: {log_entry.get('company') or 'N/A'}")
                elif log_entry['status'] == 'failed':
                    logger.info(f"    Error: {log_entry.get('error', 'Unknown')}")
            logger.info("  " + "=" * 35)

            # Get final results
            final_opportunity = results.get("Final Results")
            if not final_opportunity:
                logger.warning(f"  No final results available for message {message_id}, skipping")
                error_count += 1
                continue

            # Format row for sheet
            row = format_row_for_sheet(email_data, final_opportunity, llm_body_result, extractor_parser)

            # Append to sheet
            logger.info(f"  Appending to Google Sheet...")
            append_to_sheet(sheets_service, sheet_id, sheet_name, row)

            # Add label to mark as parsed
            add_label_to_message(gmail_service, message_id, parsed_label_id)

            # Mark as read and archive
            mark_as_read_and_archive(gmail_service, message_id)

            processed_count += 1
            logger.info(f"  ✓ Successfully processed message {message_id}")

            # Rate limiting - be nice to APIs
            time.sleep(1)

        except Exception as e:
            logger.error(f"  ✗ Error processing message {message_id}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            error_count += 1
            continue

    logger.info("\n" + "=" * 80)
    logger.info(f"Processing complete!")
    logger.info(f"  Processed: {processed_count}")
    logger.info(f"  Errors: {error_count}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()

