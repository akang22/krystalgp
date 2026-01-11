#!/bin/bash
# Cron wrapper script for Gmail parser
# This script sets up the environment and runs the Gmail parser

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Change to project directory
cd "$PROJECT_DIR" || exit 1

# Set up logging
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/gmail_parser_$(date +%Y%m%d).log"

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "Starting Gmail parser cron job"

# Load environment variables from .env file if it exists
if [ -f "$PROJECT_DIR/.env" ]; then
    # Export variables from .env file
    set -a
    source "$PROJECT_DIR/.env"
    set +a
    log "Loaded environment variables from .env"
else
    log "WARNING: .env file not found at $PROJECT_DIR/.env"
fi

# Check if uv is available
if ! command -v uv &> /dev/null; then
    log "ERROR: uv command not found. Please install uv or adjust PATH."
    exit 1
fi

# Run the parser
log "Running Gmail parser script..."
uv run python scripts/parse_gmail_forwards.py >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    log "Gmail parser completed successfully"
else
    log "ERROR: Gmail parser failed with exit code $EXIT_CODE"
fi

exit $EXIT_CODE







