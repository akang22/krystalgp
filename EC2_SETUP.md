# EC2 Server Setup for Gmail Parser

## Option 1: Copy Token from Local Machine (Easiest)

After running the script locally once and authenticating:

1. Copy `token.json` to your EC2 server:
   ```bash
   scp token.json user@your-ec2-ip:/path/to/project/
   ```

2. Make sure the credentials file is also on EC2:
   ```bash
   scp client_secret_*.apps.googleusercontent.com.json user@your-ec2-ip:/path/to/project/credentials.json
   ```

3. The token will work until it expires (usually 7 days for refresh tokens, but can be longer)

## Option 2: Use Service Account (Recommended for Production)

For a more robust setup, use a service account instead of OAuth:

1. In Google Cloud Console, create a Service Account
2. Download the service account JSON key
3. Share your Google Sheet with the service account email
4. Modify the script to use service account credentials

## Setting Up Cron Job

### Step 1: Create the cron script

Create a wrapper script that sets up the environment and runs the parser:

```bash
#!/bin/bash
# /path/to/run_gmail_parser.sh

# Set working directory
cd /path/to/krystalgp

# Load environment variables
source .env 2>/dev/null || export $(cat .env | xargs)

# Activate virtual environment (if using uv)
export PATH="/path/to/.venv/bin:$PATH"

# Run the parser
uv run python scripts/parse_gmail_forwards.py >> /path/to/logs/gmail_parser.log 2>&1
```

### Step 2: Make it executable

```bash
chmod +x /path/to/run_gmail_parser.sh
```

### Step 3: Add to crontab

```bash
crontab -e
```

Add this line to run every hour:

```
0 * * * * /path/to/run_gmail_parser.sh
```

Or run every 30 minutes:

```
*/30 * * * * /path/to/run_gmail_parser.sh
```

### Step 4: Test the cron job

```bash
# Test the script manually first
/path/to/run_gmail_parser.sh

# Check logs
tail -f /path/to/logs/gmail_parser.log
```

## Troubleshooting

- **Token expires**: You'll need to re-authenticate locally and copy the new token.json
- **Permissions**: Make sure the cron user has read access to credentials and token files
- **Environment variables**: Cron runs with minimal environment, so load them explicitly in the script
- **Path issues**: Use absolute paths in the cron script







