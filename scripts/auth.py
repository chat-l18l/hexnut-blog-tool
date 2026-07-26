"""Blogger OAuth handling.

Why: Blogger write operations require user authorization via OAuth2.
What: Obtain and cache credentials for the google-api-python-client.
Pre:  client_secrets.json or env setup (we use run_local_server).
Post: Valid credentials written to token.json (or equivalent).
"""

import os
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import json

SCOPES = ["https://www.googleapis.com/auth/blogger"]
TOKEN_FILE = Path(".token.json")  # never commit
CLIENT_SECRETS = Path("client_secrets.json")  # user must provide once

def get_credentials():
    """Return valid Credentials or raise."""
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRETS.exists():
                raise RuntimeError(
                    "client_secrets.json not found. Create OAuth client in Google Cloud Console "
                    "(Desktop app) and download it here."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
            creds = flow.run_local_server(port=0)
        # save
        TOKEN_FILE.write_text(creds.to_json())
    return creds

def run_auth():
    """CLI helper: force fresh auth."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
    creds = get_credentials()
    print("Authentication successful. Token saved.")
    print(f"Token file: {TOKEN_FILE}")
