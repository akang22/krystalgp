# Gmail API Setup Instructions

## Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click the project dropdown at the top
3. Click "New Project"
4. Enter a project name (e.g., "Email Parser")
5. Click "Create"

## Step 2: Enable APIs

1. In your project, go to "APIs & Services" > "Library"
2. Search for "Gmail API" and click it
3. Click "Enable"
4. Search for "Google Sheets API" and click it
5. Click "Enable"

## Step 3: Create OAuth Credentials

1. Go to "APIs & Services" > "Credentials"
2. Click "Create Credentials" > "OAuth client ID"
3. If prompted, configure the OAuth consent screen:
   - Choose "External" (unless you have a Google Workspace)
   - Fill in required fields (App name, User support email, Developer contact)
   - Add scopes: `https://www.googleapis.com/auth/gmail.readonly`, `https://www.googleapis.com/auth/gmail.modify`, `https://www.googleapis.com/auth/spreadsheets`
   - Add test users (your Gmail address)
   - Save
4. Back in Credentials, choose "Desktop app" as application type
5. Give it a name (e.g., "Email Parser Client")
6. Click "Create"
7. Click "Download JSON"
8. The file will be named something like `client_secret_XXXXX.apps.googleusercontent.com.json`
9. You can either:
   - **Option A (Recommended):** Rename it to `credentials.json` in your project root
   - **Option B:** Keep the original name and set `GMAIL_CREDENTIALS_PATH` to the full filename

**⚠️ SECURITY WARNING:** 
- **DO NOT** commit credentials files or `token.json` to git
- Files matching `client_secret_*.apps.googleusercontent.com.json`, `credentials.json`, and `token.json` are in `.gitignore`
- The `client_secret` in the credentials file should be kept private
- If you accidentally committed them, rotate/regenerate the credentials immediately in Google Cloud Console

## Step 4: Set Environment Variable

In your `.env` file:
```bash
GMAIL_CREDENTIALS_PATH=credentials.json
```

Or if you put it in a different location:
```bash
GMAIL_CREDENTIALS_PATH=/path/to/your/credentials.json
```

## First Run

When you first run the script, it will:
1. Open a browser window
2. Ask you to sign in with your Google account
3. Ask for permission to access Gmail and Sheets
4. Save the token to `token.json` for future runs

After the first run, you won't need to authenticate again (until the token expires).

