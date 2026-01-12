"""Script to rerun parsing logic on emails matching conditions with optional filter and limit.

This script:
1. Finds emails matching the search conditions (with optional filter)
2. Ignores the parsed label filter (can rerun on already-processed emails)
3. Supports limit parameter (1 for last email, None for all emails)
4. Uses the same parsing logic as parse_gmail_forwards.py
5. Updates Google Sheet with results

Usage:
    # Rerun last email (default)
    python scripts/rerun_emails.py
    
    # Rerun last 5 emails
    python scripts/rerun_emails.py --limit 5
    
    # Rerun all matching emails
    python scripts/rerun_emails.py --limit None
    
    # Rerun with additional filter (e.g., subject contains "Project Wave")
    python scripts/rerun_emails.py --filter "subject:Project Wave" --limit None

Useful for debugging or reprocessing emails.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Load environment variables
load_dotenv()

# Import all the reusable functions from parse_gmail_forwards
# We'll import the module and use its functions
import parse_gmail_forwards

from email_parser.base import BaseParser, ParserResult
from email_parser.ensemble_parser import EnsembleParser
from email_parser.layout_attachment_parser import LayoutLLMParser
from email_parser.llm_body_parser import LLMBodyParser
from email_parser.ocr_attachment_parser import OCRAttachmentParser

logger = parse_gmail_forwards.logger


def search_emails_with_filter(
    gmail_service: Any,
    search_patterns: str,
    recipient_filter: Optional[str] = None,
    additional_filter: Optional[str] = None,
    limit: Optional[int] = 1,
) -> List[Dict[str, Any]]:
    """Search for emails matching conditions with optional filter and limit.
    
    This is similar to search_gmail_forwards but:
    - Does NOT exclude the parsed label (can find already-processed emails)
    - Supports additional filter string
    - Supports limit parameter (None = all emails with pagination)
    
    Args:
        gmail_service: Gmail API service object
        search_patterns: Email search patterns (from env)
        recipient_filter: Recipient email address to filter by
        additional_filter: Additional Gmail search filter (e.g., "subject:Project Wave")
        limit: Maximum number of results (None = all, default 1 for last email)
        
    Returns:
        List of message dicts
    """
    # Build base query WITHOUT the parsed label exclusion
    base_query = parse_gmail_forwards.build_gmail_search_query(
        search_patterns=search_patterns,
        parsed_label_name=None,  # Don't exclude parsed emails
        recipient_filter=recipient_filter,
    )
    
    # Add additional filter if provided
    if additional_filter:
        query = f"({base_query}) {additional_filter}"
    else:
        query = base_query
    
    logger.info(f"Searching for emails with query: {query}")
    if limit:
        logger.info(f"Limit: {limit} email(s)")
    else:
        logger.info("Limit: None (processing all matching emails)")
    
    try:
        all_messages = []
        page_token = None
        
        # If limit is None, we need to paginate through all results
        # Gmail API maxResults per page is 500
        max_results_per_page = 500
        
        while True:
            # Determine how many to fetch in this page
            if limit is None:
                # Fetch full page, we'll stop when no more results
                fetch_count = max_results_per_page
            else:
                # Fetch only what we need
                remaining = limit - len(all_messages)
                if remaining <= 0:
                    break
                fetch_count = min(remaining, max_results_per_page)
            
            # Build request
            request_params = {
                "userId": "me",
                "q": query,
                "maxResults": fetch_count,
            }
            if page_token:
                request_params["pageToken"] = page_token
            
            # Execute request
            results = (
                gmail_service.users()
                .messages()
                .list(**request_params)
                .execute()
            )
            
            messages = results.get("messages", [])
            all_messages.extend(messages)
            
            logger.info(f"Found {len(messages)} messages in this page (total: {len(all_messages)})")
            
            # Check if we should continue
            if limit is not None and len(all_messages) >= limit:
                # We've reached the limit
                all_messages = all_messages[:limit]
                break
            
            # Check if there are more pages
            page_token = results.get("nextPageToken")
            if not page_token:
                # No more pages
                break
        
        logger.info(f"Found {len(all_messages)} message(s) total")
        return all_messages
        
    except Exception as error:
        logger.error(f"Error searching Gmail: {error}")
        raise


def process_single_email(
    gmail_service: Any,
    sheets_service: Any,
    message_id: str,
    parsers: Dict[str, BaseParser],
    parsed_label_id: Optional[str] = None,
    update_label: bool = False,
    mark_read: bool = False,
) -> bool:
    """Process a single email using the same logic as parse_gmail_forwards.
    
    Args:
        gmail_service: Gmail API service object
        sheets_service: Google Sheets API service object
        message_id: Gmail message ID
        parsers: Dict of parser name to parser instance
        parsed_label_id: Label ID to add (optional)
        update_label: Whether to add the label after processing
        mark_read: Whether to mark as read and archive after processing
        
    Returns:
        True if successful, False otherwise
    """
    import time
    
    logger.info(f"Processing message {message_id}...")
    
    try:
        # Get full message
        full_message = parse_gmail_forwards.get_message_details(gmail_service, message_id)
        
        # Use any available parser for email extraction
        extractor_parser = list(parsers.values())[0]
        
        # Extract email data from Gmail message (pass gmail_service for large attachments)
        email_data = extractor_parser.extract_gmail_message(full_message, gmail_service=gmail_service)
        
        logger.info(f"  Subject: {email_data.subject}")
        logger.info(f"  From: {email_data.sender}")
        logger.info(f"  Attachments: {len(email_data.attachments)}")
        
        # Run parsers (same logic as main script)
        results = {}
        llm_body_result = None
        parser_execution_log = {}
        
        logger.info("  === Running Parsers ===")
        for parser_name, parser in parsers.items():
            parser_start_time = time.time()
            try:
                result = parser.parse_data(email_data)
                parser_time = time.time() - parser_start_time
                
                results[parser_name] = result
                parser_execution_log[parser_name] = {
                    "status": "success",
                    "method": "parse_data",
                    "time": parser_time,
                    "ebitda": result.ebitda_millions,
                    "company": result.company_name,
                }
                
                if parser_name == "LLM Body":
                    llm_body_result = ParserResult(
                        opportunity=result,
                        parser_name="LLM Body",
                        processing_time_seconds=parser_time,
                        extraction_source="body",
                    )
                
                # Log extraction results
                ebitda_str = f"${result.ebitda_millions:.1f}M" if result.ebitda_millions else "No EBITDA"
                logger.info(f"  ✓ {parser_name}: {ebitda_str}")
                logger.info(f"    Processing time: {parser_time:.2f}s")
                logger.info(f"    Company: {result.company_name or 'N/A'}")
                logger.info(f"    Location: {result.hq_location or 'N/A'}")
                logger.info(f"    Sector: {result.sector or 'N/A'}")
                
            except Exception as e:
                parser_time = time.time() - parser_start_time
                logger.error(f"  ✗ {parser_name} failed: {e}")
                parser_execution_log[parser_name] = {
                    "status": "failed",
                    "method": "parse_data",
                    "time": parser_time,
                    "error": str(e),
                }
        
        # Get final results from ensemble parser
        if "Final Results" in results:
            final_opportunity = results["Final Results"]
            logger.info("  ✓ Final Results: " + (f"EBITDA=${final_opportunity.ebitda_millions:.1f}M" if final_opportunity.ebitda_millions else "No EBITDA"))
            logger.info(f"    Processing time: {parser_execution_log.get('Final Results', {}).get('time', 0):.2f}s")
            logger.info(f"    Company: {final_opportunity.company_name or 'N/A'}")
            logger.info(f"    Location: {final_opportunity.hq_location or 'N/A'}")
            logger.info(f"    Sector: {final_opportunity.sector or 'N/A'}")
        
        # Format for sheet
        sheet_id = os.getenv("GOOGLE_SHEET_ID")
        sheet_name = os.getenv("GOOGLE_SHEET_NAME", "Sheet1")
        
        if sheet_id and "Final Results" in results:
            row = parse_gmail_forwards.format_row_for_sheet(
                email_data, final_opportunity, llm_body_result, extractor_parser
            )
            
            logger.info("  Appending to Google Sheet...")
            parse_gmail_forwards.append_to_sheet(sheets_service, sheet_id, sheet_name, row)
            logger.info(f"  ✓ Appended row to sheet: {final_opportunity.company_name or 'N/A'}")
        
        # Optionally update label and mark as read
        if update_label and parsed_label_id:
            parse_gmail_forwards.add_label_to_message(gmail_service, message_id, parsed_label_id)
            logger.info(f"  ✓ Added label to message {message_id}")
        
        if mark_read:
            parse_gmail_forwards.mark_as_read_and_archive(gmail_service, message_id)
            logger.info(f"  ✓ Marked as read and archived message {message_id}")
        
        logger.info(f"  ✓ Successfully processed message {message_id}")
        return True
        
    except Exception as e:
        logger.error(f"  ✗ Error processing message {message_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def main():
    """Main function to rerun parsing on emails with filter and limit."""
    parser = argparse.ArgumentParser(
        description="Rerun parsing logic on emails matching conditions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Rerun last email (default)
  python scripts/rerun_emails.py
  
  # Rerun last 5 emails
  python scripts/rerun_emails.py --limit 5
  
  # Rerun all matching emails
  python scripts/rerun_emails.py --limit None
  
  # Rerun with additional filter
  python scripts/rerun_emails.py --filter "subject:Project Wave" --limit None
        """
    )
    
    parser.add_argument(
        "--limit",
        type=lambda x: None if x.lower() == "none" else int(x),
        default=1,
        help="Maximum number of emails to process (default: 1 for last email, None for all)",
    )
    
    parser.add_argument(
        "--filter",
        type=str,
        default=None,
        help="Additional Gmail search filter (e.g., 'subject:Project Wave')",
    )
    
    parser.add_argument(
        "--update-label",
        action="store_true",
        help="Add parsed label after processing",
    )
    
    parser.add_argument(
        "--mark-read",
        action="store_true",
        help="Mark emails as read and archive after processing",
    )
    
    args = parser.parse_args()
    
    logger.info("=" * 80)
    logger.info("Rerun Emails Parser - Starting")
    logger.info("=" * 80)
    
    # Get configuration from environment (same as main script)
    search_patterns = os.getenv("GMAIL_SEARCH_DOMAIN") or os.getenv("GMAIL_SEARCH_PATTERNS")
    if not search_patterns:
        logger.error(
            "GMAIL_SEARCH_DOMAIN or GMAIL_SEARCH_PATTERNS environment variable not set. "
            "Examples: 'kpmg.com', '*@krystalgp.com', 'user@example.com', 'kpmg.com *@krystalgp.com'"
        )
        sys.exit(1)
    
    recipient_filter = os.getenv("GMAIL_RECIPIENT_FILTER")
    parsed_label_name = os.getenv("GMAIL_PARSED_LABEL", "ParsedByEmailParser")
    
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not sheet_id:
        logger.error("GOOGLE_SHEET_ID environment variable not set")
        sys.exit(1)
    
    # Extract sheet ID from URL if full URL provided
    if "/spreadsheets/d/" in sheet_id:
        sheet_id = sheet_id.split("/spreadsheets/d/")[1].split("/")[0]
    
    logger.info(f"Configuration:")
    logger.info(f"  Search Patterns: {search_patterns}")
    logger.info(f"  Recipient Filter: {recipient_filter or 'None (all recipients)'}")
    logger.info(f"  Additional Filter: {args.filter or 'None'}")
    logger.info(f"  Limit: {args.limit if args.limit is not None else 'None (all emails)'}")
    logger.info(f"  Note: Parsed label filter is IGNORED (will find already-processed emails)")
    logger.info(f"  Sheet ID: {sheet_id}")
    logger.info(f"  Update Label: {args.update_label}")
    logger.info(f"  Mark Read: {args.mark_read}")
    
    # Authenticate
    logger.info("\nAuthenticating with Gmail API...")
    gmail_service = parse_gmail_forwards.authenticate_gmail()
    
    logger.info("Authenticating with Google Sheets API...")
    sheets_service = parse_gmail_forwards.authenticate_sheets()
    
    # Get parsed label ID (optional, for adding label)
    parsed_label_id = None
    if parsed_label_name:
        logger.info(f"\nManaging label: {parsed_label_name}")
        parsed_label_id = parse_gmail_forwards.get_or_create_label(gmail_service, parsed_label_name)
    
    # Search for emails (ignoring parsed label)
    logger.info(f"\nSearching for emails matching: {search_patterns}...")
    messages = search_emails_with_filter(
        gmail_service=gmail_service,
        search_patterns=search_patterns,
        recipient_filter=recipient_filter,
        additional_filter=args.filter,
        limit=args.limit,
    )
    
    if not messages:
        logger.info("No emails found matching conditions")
        return
    
    logger.info(f"Found {len(messages)} email(s) to process")
    
    # Initialize parsers (same as main script)
    logger.info("\nInitializing parsers...")
    parsers = {}
    
    try:
        parsers["LLM Body"] = LLMBodyParser()
        logger.info("  ✓ LLM Body Parser initialized")
    except Exception as e:
        logger.warning(f"  ✗ LLM Body Parser: {e}")
    
    try:
        parsers["OCR + LLM"] = OCRAttachmentParser()
        logger.info("  ✓ OCR + LLM Parser initialized")
    except Exception as e:
        logger.warning(f"  ✗ OCR + LLM Parser: {e}")
    
    try:
        parsers["Layout Vision"] = LayoutLLMParser()
        logger.info("  ✓ Layout Vision Parser initialized")
    except Exception as e:
        logger.warning(f"  ✗ Layout Vision Parser: {e}")
    
    try:
        parsers["Final Results"] = EnsembleParser(use_llm=True, use_vision=True, use_ocr=False)
        logger.info("  ✓ Ensemble Parser initialized")
    except Exception as e:
        logger.warning(f"  ✗ Ensemble Parser: {e}")
    
    if not parsers:
        logger.error("No parsers available. Check your configuration.")
        sys.exit(1)
    
    # Process all emails
    logger.info(f"\nProcessing {len(messages)} email(s)...")
    success_count = 0
    error_count = 0
    
    for idx, message in enumerate(messages, 1):
        message_id = message["id"]
        logger.info(f"\n[{idx}/{len(messages)}] Processing message {message_id}...")
        
        success = process_single_email(
            gmail_service=gmail_service,
            sheets_service=sheets_service,
            message_id=message_id,
            parsers=parsers,
            parsed_label_id=parsed_label_id,
            update_label=args.update_label,
            mark_read=args.mark_read,
        )
        
        if success:
            success_count += 1
        else:
            error_count += 1
    
    logger.info("\n" + "=" * 80)
    logger.info("Processing complete!")
    logger.info(f"  Processed: {len(messages)}")
    logger.info(f"  Successful: {success_count}")
    logger.info(f"  Errors: {error_count}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
