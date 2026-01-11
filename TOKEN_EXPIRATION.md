# OAuth Token Expiration and Refresh

## How Token Expiration Works

### Access Tokens
- **Lifetime**: ~1 hour
- **Auto-refresh**: ✅ The script automatically refreshes these using the refresh token
- **No action needed**: The Google API client library handles this automatically

### Refresh Tokens
- **Lifetime for unverified/dev OAuth apps**: 7 days of inactivity
- **Lifetime for verified apps**: Can last indefinitely (or until revoked)
- **What happens**: If the refresh token expires, you need to re-authenticate

## Current Script Behavior

The script **already handles automatic refresh**:

```python
# Lines 119-121 in parse_gmail_forwards.py
if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())  # ← Automatically refreshes access token
```

**What this means:**
- ✅ Access tokens are automatically refreshed when expired
- ✅ As long as the refresh token is valid, no manual intervention needed
- ⚠️ If refresh token expires (7 days of inactivity for dev apps), you'll need to re-authenticate

## Solutions for Long-Running EC2 Servers

### Option 1: Keep the App Active (Easiest)

Since refresh tokens expire after **7 days of inactivity** for dev apps, running the cron job **at least once every 6 days** keeps the refresh token alive:

```bash
# Run every hour (keeps token alive)
0 * * * * /path/to/run_gmail_parser_cron.sh

# Or at minimum, run every 6 days
0 0 */6 * * /path/to/run_gmail_parser_cron.sh
```

**This is the simplest solution** - the hourly cron job will keep refreshing the token automatically.

### Option 2: Verify Your OAuth App (Best for Production)

For verified OAuth apps, refresh tokens can last indefinitely:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. APIs & Services > OAuth consent screen
3. Complete the verification process:
   - Add app information
   - Add privacy policy URL
   - Add terms of service URL
   - Submit for verification (if needed)

**Benefits:**
- Refresh tokens don't expire after 7 days
- More professional/trusted app
- Better for production use

### Option 3: Use Service Account (Most Robust)

Service accounts don't use OAuth tokens - they use service account keys that don't expire:

1. Create a Service Account in Google Cloud Console
2. Download the service account JSON key
3. Share your Google Sheet with the service account email
4. Modify the script to use service account credentials

**Benefits:**
- No token expiration issues
- No user interaction needed
- Best for automated servers

**Drawback:**
- Requires modifying the authentication code in the script

### Option 4: Monitor Token Expiration

Add monitoring/alerting for when refresh fails:

```python
try:
    creds.refresh(Request())
except Exception as e:
    # Send alert/email when refresh fails
    logger.error(f"Token refresh failed: {e}")
    # Could send email notification here
```

## Recommended Approach

For your EC2 server running hourly:

1. **Short term**: The hourly cron job will keep the refresh token alive (runs more than once every 7 days)
2. **Long term**: Consider verifying your OAuth app or switching to a service account

The current setup should work fine as long as the cron job runs regularly!







