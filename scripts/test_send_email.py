"""Test script to send an email with attachments from hello@photoncollective.dev.

This script:
1. Takes a .msg email file as input
2. Extracts the email content and attachments
3. Sends it via Gmail API from hello@photoncollective.dev
4. Sends to andrewkang.ubc2020@gmail.com for testing

Usage:
    uv run python scripts/test_send_email.py <path_to_msg_file>
"""

import argparse
import base64
import email
import email.mime
import email.mime.base
import email.mime.multipart
import email.mime.text
import logging
import os
import sys
from pathlib import Path
from typing import Any, List, Optional

from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

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

# Gmail API scopes (need send permission)
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",  # For reading message structure
]


def authenticate_gmail(credentials_path: str, token_path: str):
    """Authenticate and return Gmail service.

    Args:
        credentials_path: Path to OAuth credentials JSON file
        token_path: Path to save/load OAuth token

    Returns:
        Gmail API service object

    Raises:
        Exception: If authentication fails
    """
    creds = None

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
                    "Please provide the OAuth credentials file for hello@photoncollective.dev"
                )
                raise FileNotFoundError(f"Credentials file not found: {credentials_path}")

            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save credentials for next run
        with open(token_path, "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def extract_msg_content(msg_path: Path):
    """Extract content from .msg file.

    Args:
        msg_path: Path to .msg file

    Returns:
        Tuple of (subject, body_plain, body_html, attachments)
    """
    try:
        import extract_msg

        msg = extract_msg.Message(msg_path)

        subject = msg.subject or ""
        body_plain = msg.body or ""
        body_html = msg.htmlBody or ""

        # Extract attachments
        attachments = []
        for attachment in msg.attachments:
            attachments.append(
                {
                    "filename": attachment.longFilename or attachment.shortFilename,
                    "data": attachment.data,
                    "mime_type": attachment.mimetype or "application/octet-stream",
                }
            )

        return subject, body_plain, body_html, attachments

    except ImportError:
        logger.error("extract_msg library not installed. Run: uv pip install extract-msg")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error extracting .msg file: {e}")
        raise


def create_message(
    sender: str,
    to: str,
    subject: str,
    body_plain: str,
    body_html: Optional[str] = None,
    attachments: List[dict] = None,
) -> dict:
    """Create a message for an email.

    Args:
        sender: Email address of sender
        to: Email address of recipient
        subject: Subject line
        body_plain: Plain text body
        body_html: HTML body (optional)
        attachments: List of attachment dicts with 'filename', 'data', 'mime_type'

    Returns:
        Message dict for Gmail API
    """
    message = email.mime.multipart.MIMEMultipart("alternative")
    message["to"] = to
    message["from"] = sender
    message["subject"] = subject

    # Add plain text body
    if body_plain:
        # Decode if bytes
        if isinstance(body_plain, bytes):
            body_plain = body_plain.decode("utf-8", errors="ignore")
        part1 = email.mime.text.MIMEText(body_plain, "plain")
        message.attach(part1)

    # Add HTML body if available
    if body_html:
        # Decode if bytes
        if isinstance(body_html, bytes):
            body_html = body_html.decode("utf-8", errors="ignore")
        part2 = email.mime.text.MIMEText(body_html, "html")
        message.attach(part2)

    # Add attachments
    if attachments:
        # Change to mixed multipart to support attachments
        if (
            isinstance(message, email.mime.multipart.MIMEMultipart)
            and message.get_content_subtype() == "alternative"
        ):
            # Create a new mixed multipart container
            msg_root = email.mime.multipart.MIMEMultipart("mixed")
            msg_root["to"] = message["to"]
            msg_root["from"] = message["from"]
            msg_root["subject"] = message["subject"]

            # Attach the alternative part (text + html)
            msg_alt = email.mime.multipart.MIMEMultipart("alternative")
            for part in message.get_payload():
                msg_alt.attach(part)
            msg_root.attach(msg_alt)

            message = msg_root

        for attachment in attachments:
            part = email.mime.base.MIMEBase(*attachment["mime_type"].split("/"))
            part.set_payload(attachment["data"])
            email.encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{attachment["filename"]}"',
            )
            message.attach(part)

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {"raw": raw_message}


def send_message(gmail_service: Any, user_id: str, message: dict) -> dict:
    """Send an email message.

    Args:
        gmail_service: Gmail API service object
        user_id: User's email address (usually "me")
        message: Message dict from create_message

    Returns:
        Sent message dict
    """
    try:
        message = gmail_service.users().messages().send(userId=user_id, body=message).execute()
        logger.info(f"Message sent. Message ID: {message['id']}")
        return message
    except HttpError as error:
        logger.error(f"An error occurred: {error}")
        raise


def main():
    """Main function to send test email."""
    parser = argparse.ArgumentParser(
        description="Send test email with attachments from hello@photoncollective.dev"
    )
    parser.add_argument("msg_file", type=Path, help="Path to .msg file to send")
    parser.add_argument(
        "--credentials",
        type=str,
        default=os.getenv(
            "GMAIL_TEST_CREDENTIALS_PATH", "client_secret_*.apps.googleusercontent.com.json"
        ),
        help="Path to OAuth credentials JSON (default: client_secret_*.json)",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=os.getenv("GMAIL_TEST_TOKEN_PATH", "token_test_hello.json"),
        help="Path to save OAuth token (default: token_test_hello.json)",
    )
    parser.add_argument(
        "--from",
        dest="from_email",
        type=str,
        default="hello@photoncollective.dev",
        help="Sender email address (default: hello@photoncollective.dev)",
    )
    parser.add_argument(
        "--to",
        type=str,
        default="andrewkang.ubc2020@gmail.com",
        help="Recipient email address (default: andrewkang.ubc2020@gmail.com)",
    )

    args = parser.parse_args()

    if not args.msg_file.exists():
        logger.error(f"Email file not found: {args.msg_file}")
        sys.exit(1)

    # Find credentials file if wildcard pattern
    credentials_path = args.credentials
    if "*" in credentials_path:
        import glob

        matches = glob.glob(str(Path(__file__).parent.parent / credentials_path))
        if not matches:
            logger.error(f"No credentials file matching pattern: {credentials_path}")
            sys.exit(1)
        credentials_path = matches[0]
        logger.info(f"Using credentials file: {credentials_path}")

    logger.info("=" * 80)
    logger.info("Test Email Sender - Starting")
    logger.info("=" * 80)
    logger.info(f"Email file: {args.msg_file}")
    logger.info(f"From: {args.from_email}")
    logger.info(f"To: {args.to}")
    logger.info(f"Credentials: {credentials_path}")

    # Extract email content
    logger.info("\nExtracting email content from .msg file...")
    subject, body_plain, body_html, attachments = extract_msg_content(args.msg_file)

    logger.info(f"Subject: {subject}")
    logger.info(f"Body plain length: {len(body_plain)} chars")
    logger.info(f"Body HTML length: {len(body_html)} chars")
    logger.info(f"Attachments: {len(attachments)}")

    # Authenticate
    logger.info("\nAuthenticating with Gmail API...")
    gmail_service = authenticate_gmail(credentials_path, args.token)

    # Create message
    logger.info("\nCreating email message...")
    message = create_message(
        sender=args.from_email,
        to=args.to,
        subject=subject,
        body_plain=body_plain,
        body_html=body_html,
        attachments=attachments,
    )

    # Send message
    logger.info("\nSending email...")
    send_message(gmail_service, "me", message)

    logger.info("\n" + "=" * 80)
    logger.info("Email sent successfully!")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
