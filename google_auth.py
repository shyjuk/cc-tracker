import os
import io
import json
from typing import Optional, Tuple, Dict, Any
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
from database import get_setting, set_setting

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.readonly"
]

def get_client_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Retrieves Google OAuth Client ID and Secret from database settings or .env."""
    client_id = get_setting("google_client_id") or os.getenv("GOOGLE_CLIENT_ID")
    client_secret = get_setting("google_client_secret") or os.getenv("GOOGLE_CLIENT_SECRET")
    return client_id, client_secret

def has_google_oauth_configured() -> bool:
    """Checks if Client ID and Secret are configured."""
    client_id, client_secret = get_client_credentials()
    return bool(client_id and client_secret)

def get_oauth_flow(redirect_uri: str) -> Flow:
    """Initializes and returns the Google OAuth Flow instance."""
    client_id, client_secret = get_client_credentials()
    if not client_id or not client_secret:
        raise ValueError("Google Client ID or Client Secret is not configured. Please set them in .env or via Setup.")

    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri]
        }
    }

    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    return flow

def create_authorization_url(redirect_uri: str, state: Optional[str] = None) -> Tuple[str, str, Optional[str]]:
    """Generates the Google OAuth authorization URL requesting offline access with PKCE support."""
    flow = get_oauth_flow(redirect_uri)
    auth_url, flow_state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state
    )
    code_verifier = getattr(flow, "code_verifier", None)
    return auth_url, flow_state, code_verifier

def exchange_code_for_tokens(code: str, redirect_uri: str, code_verifier: Optional[str] = None) -> Dict[str, Any]:
    """Exchanges an authorization code for credentials and user identity with PKCE verifier."""
    flow = get_oauth_flow(redirect_uri)
    if not code_verifier:
        code_verifier = get_setting("oauth_code_verifier")
    
    if code_verifier:
        flow.code_verifier = code_verifier

    flow.fetch_token(code=code)
    creds = flow.credentials

    # Extract user profile information
    user_info_service = build("oauth2", "v2", credentials=creds)
    user_info = user_info_service.userinfo().get().execute()

    return {
        "email": user_info.get("email"),
        "name": user_info.get("name"),
        "picture": user_info.get("picture"),
        "refresh_token": creds.refresh_token,
        "access_token": creds.token
    }

def get_google_credentials() -> Optional[Credentials]:
    """
    Constructs an authorized Google Credentials object using the stored refresh_token.
    Automatically refreshes the access token if expired.
    """
    refresh_token = get_setting("google_refresh_token")
    if not refresh_token:
        return None

    client_id, client_secret = get_client_credentials()
    if not client_id or not client_secret:
        return None

    creds = Credentials(
        token=get_setting("google_access_token"),
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret
    )

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            if creds.token:
                set_setting("google_access_token", creds.token)
        except Exception as e:
            print(f"Failed to refresh Google OAuth token: {e}")
            return None

    return creds

def get_drive_service(creds: Optional[Credentials] = None):
    """Returns an authorized Google Drive API client."""
    credentials = creds or get_google_credentials()
    if not credentials:
        raise ValueError("Google OAuth credentials not available. Please sign in with Google.")
    return build("drive", "v3", credentials=credentials)

def get_sheets_service(creds: Optional[Credentials] = None):
    """Returns an authorized Google Sheets API client."""
    credentials = creds or get_google_credentials()
    if not credentials:
        raise ValueError("Google OAuth credentials not available. Please sign in with Google.")
    return build("sheets", "v4", credentials=credentials)

def get_gmail_service(creds: Optional[Credentials] = None):
    """Returns an authorized Gmail API client."""
    credentials = creds or get_google_credentials()
    if not credentials:
        raise ValueError("Google OAuth credentials not available. Please sign in with Google.")
    return build("gmail", "v1", credentials=credentials)

def provision_spreadsheet_from_template(
    file_bytes_or_path: Any,
    title: str = "Credit Card Payment Tracker",
    creds: Optional[Credentials] = None
) -> Dict[str, Any]:
    """
    Uploads an .xlsx Excel template file to Google Drive and converts it
    into a native Google Sheet. Returns spreadsheet ID, name, URL, and tab names.
    """
    drive = get_drive_service(creds)
    sheets = get_sheets_service(creds)

    file_metadata = {
        "name": title,
        "mimeType": "application/vnd.google-apps.spreadsheet"  # Requests native conversion
    }

    if isinstance(file_bytes_or_path, (bytes, bytearray)):
        media = MediaIoBaseUpload(
            io.BytesIO(file_bytes_or_path),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            resumable=True
        )
    elif isinstance(file_bytes_or_path, str) and os.path.exists(file_bytes_or_path):
        media = MediaFileUpload(
            file_bytes_or_path,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            resumable=True
        )
    else:
        raise ValueError("Invalid template source provided.")

    # 1. Create file on Google Drive (converted to Sheet)
    created_file = drive.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, name, webViewLink"
    ).execute()

    sheet_id = created_file.get("id")
    sheet_name = created_file.get("name")
    sheet_url = created_file.get("webViewLink")

    # 2. Inspect tabs in newly created spreadsheet
    sheet_meta = sheets.spreadsheets().get(spreadsheetId=sheet_id).execute()
    tabs = [s["properties"]["title"] for s in sheet_meta.get("sheets", [])]

    # 3. Store in application settings
    set_setting("spreadsheet_id", sheet_id)
    set_setting("spreadsheet_name", sheet_name)
    set_setting("spreadsheet_url", sheet_url)
    set_setting("spreadsheet_tabs", json.dumps(tabs))

    return {
        "success": True,
        "spreadsheet_id": sheet_id,
        "spreadsheet_name": sheet_name,
        "spreadsheet_url": sheet_url,
        "tabs": tabs
    }
