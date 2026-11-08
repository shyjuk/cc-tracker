import os
import json
import secrets
from typing import Optional
from urllib.parse import quote
from fastapi import APIRouter, Request, Response, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from database import SessionLocal, User, get_setting, set_setting
from google_auth import (
    has_google_oauth_configured,
    get_client_credentials,
    create_authorization_url,
    exchange_code_for_tokens,
    get_google_credentials,
    get_sheets_service,
    get_gmail_service,
    provision_spreadsheet_from_template
)
from auth import create_access_token, get_current_user, get_optional_user, is_request_secure

router = APIRouter(tags=["Google SSO & Automated Setup"])

class ClientCredentialsSchema(BaseModel):
    client_id: str
    client_secret: str

class VerifySetupSchema(BaseModel):
    gmail_label: Optional[str] = "Statements"

def get_redirect_uri(request: Request) -> str:
    """Builds the canonical OAuth redirect URI matching the current browser request host."""
    # Detect incoming host and proto from reverse proxy headers (Render, Cloudflare, etc.)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"

    # Local development: if browser accessed via localhost or 127.0.0.1
    if "127.0.0.1" in host or "localhost" in host:
        env_uri = os.getenv("GOOGLE_REDIRECT_URI")
        if env_uri:
            return env_uri
        port = request.url.port or 8000
        host_name = host.split(":")[0]
        return f"http://{host_name}:{port}/api/auth/google/callback"

    # Cloud / Production environment (Render, FastAPI Cloud, etc.):
    # If GOOGLE_REDIRECT_URI is explicitly set to a production domain (not localhost), honor it
    env_uri = os.getenv("GOOGLE_REDIRECT_URI")
    if env_uri and "localhost" not in env_uri and "127.0.0.1" not in env_uri:
        return env_uri

    # Otherwise automatically build from the live incoming public HTTPS domain
    return f"{proto}://{host}/api/auth/google/callback"

@router.get("/api/setup/status")
def get_setup_status(request: Request):
    """Returns the current setup and Google connection status.
    After setup is completed, requires an authenticated session to avoid
    leaking owner_email and spreadsheet_id to unauthenticated callers.
    """
    setup_done = get_setting("setup_completed") == "true"
    load_dotenv(override=True)
    allow_reset = os.getenv("ENABLE_SETUP_WIZARD_RESET", "false").lower() in ("true", "1", "yes")

    if setup_done:
        # Lightweight auth check — no hard dependency to keep the wizard working
        db = SessionLocal()
        try:
            user = get_optional_user(request, db)
        finally:
            db.close()
        if not user:
            # Return only the minimum needed for the login page redirect logic
            return {
                "has_client_credentials": has_google_oauth_configured(),
                "setup_completed": True,
                "has_google_token": bool(get_setting("google_refresh_token")),
                "owner_email": None,
                "spreadsheet_id": None,
                "spreadsheet_name": None,
                "spreadsheet_url": None,
                "gmail_label": None,
                "allow_setup_reset": allow_reset,
            }

    has_creds = has_google_oauth_configured()
    owner_email = get_setting("owner_email")
    has_token = bool(get_setting("google_refresh_token"))
    sheet_id = get_setting("spreadsheet_id")
    sheet_name = get_setting("spreadsheet_name", "Credit Card Payment Tracker")
    sheet_url = get_setting("spreadsheet_url")
    gmail_label = get_setting("gmail_label", "Statements")

    return {
        "has_client_credentials": has_creds,
        "setup_completed": setup_done,
        "owner_email": owner_email,
        "has_google_token": has_token,
        "spreadsheet_id": sheet_id,
        "spreadsheet_name": sheet_name,
        "spreadsheet_url": sheet_url,
        "gmail_label": gmail_label,
        "allow_setup_reset": allow_reset,
    }

@router.post("/api/setup/credentials")
def save_client_credentials(payload: ClientCredentialsSchema):
    """Saves Google OAuth Client ID and Secret if not present in .env."""
    cid = payload.client_id.strip()
    csec = payload.client_secret.strip()
    if not cid or not csec:
        raise HTTPException(status_code=400, detail="Client ID and Client Secret are required.")

    set_setting("google_client_id", cid)
    set_setting("google_client_secret", csec)
    return {"success": True, "message": "Google Client credentials saved successfully."}

@router.post("/api/setup/upload-client-secret")
async def upload_client_secret(file: UploadFile = File(...)):
    """
    Parses an uploaded Google Cloud Console client_secret_*.json file,
    extracts client_id and client_secret, verifies redirect_uris,
    and saves credentials to database settings.
    """
    # Enforce a strict file size limit — real client_secret.json is always < 5 KB
    MAX_SIZE = 64 * 1024  # 64 KB
    try:
        content = await file.read(MAX_SIZE + 1)
        if len(content) > MAX_SIZE:
            raise HTTPException(status_code=413, detail="File too large. A valid client_secret.json must be under 64 KB.")
        data = json.loads(content.decode("utf-8"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON file format: {str(e)}")

    # Must have a 'web' or 'installed' top-level key — do NOT fall back to raw dict
    client_info = data.get("web") or data.get("installed")
    if not client_info:
        raise HTTPException(
            status_code=400,
            detail="Invalid credentials file. The JSON must contain a 'web' or 'installed' key. "
                   "Ensure you downloaded the OAuth 2.0 Client credentials from Google Cloud Console."
        )

    client_id = client_info.get("client_id")
    client_secret = client_info.get("client_secret")
    project_id = client_info.get("project_id", "")
    redirect_uris = client_info.get("redirect_uris", [])

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=400,
            detail="Could not find 'client_id' and 'client_secret' in the uploaded JSON file. Ensure you downloaded the OAuth 2.0 Client credentials file from Google Cloud Console."
        )

    # Validate redirect URIs
    expected_local = "http://localhost:8000/api/auth/google/callback"
    expected_ip = "http://127.0.0.1:8000/api/auth/google/callback"
    has_callback = any(expected_local in uri or expected_ip in uri for uri in redirect_uris)

    warning_msg = None
    if not has_callback:
        warning_msg = (
            f"Your client_secret.json does not list '{expected_local}' under redirect_uris. "
            f"Please ensure you add '{expected_local}' and '{expected_ip}' to 'Authorized redirect URIs' in Google Cloud Console."
        )

    set_setting("google_client_id", client_id.strip())
    set_setting("google_client_secret", client_secret.strip())
    if project_id:
        set_setting("google_project_id", project_id.strip())

    return {
        "success": True,
        "message": f"Successfully loaded credentials for project '{project_id or 'Google Cloud'}'!",
        "client_id": client_id,
        "project_id": project_id,
        "redirect_uris": redirect_uris,
        "has_required_redirect_uri": has_callback,
        "warning": warning_msg
    }

@router.get("/api/auth/google/login")
def google_login(request: Request):
    """Initiates Google OAuth 2.0 flow and redirects the user to Google's consent screen."""
    if not has_google_oauth_configured():
        return RedirectResponse(url="/login?error=missing_client_credentials")

    redirect_uri = get_redirect_uri(request)

    # Generate a CSRF state token and pass it into the auth URL
    csrf_state = secrets.token_urlsafe(32)
    auth_url, _, code_verifier = create_authorization_url(redirect_uri, state=csrf_state)

    if code_verifier:
        set_setting("oauth_code_verifier", code_verifier)

    redirect = RedirectResponse(url=auth_url)

    # Store state in a short-lived HttpOnly cookie for validation on callback
    is_sec = is_request_secure(request)
    redirect.set_cookie(
        key="oauth_state",
        value=csrf_state,
        httponly=True,
        max_age=600,
        samesite="lax",
        secure=is_sec
    )
    if code_verifier:
        redirect.set_cookie(
            key="oauth_code_verifier",
            value=code_verifier,
            httponly=True,
            max_age=600,
            samesite="lax",
            secure=is_sec
        )
    return redirect

@router.get("/api/auth/google/callback")
def google_callback(request: Request, response: Response, code: Optional[str] = None, error: Optional[str] = None, state: Optional[str] = None):
    """Handles the OAuth 2.0 callback from Google."""
    if error:
        return RedirectResponse(url=f"/login?error={quote(error)}")

    if not code:
        return RedirectResponse(url="/login?error=missing_code")

    # --- C2: Validate CSRF state ---
    expected_state = request.cookies.get("oauth_state")
    if not expected_state or not secrets.compare_digest(expected_state, state or ""):
        return RedirectResponse(url="/login?error=invalid_state")

    try:
        redirect_uri = get_redirect_uri(request)
        code_verifier = request.cookies.get("oauth_code_verifier") or get_setting("oauth_code_verifier")
        tokens = exchange_code_for_tokens(code, redirect_uri, code_verifier=code_verifier)

        # H4: Clear PKCE verifier immediately after use (single-use)
        set_setting("oauth_code_verifier", "")

        email = tokens.get("email")
        if not email:
            return RedirectResponse(url="/login?error=no_email_returned")

        # Ensure User record exists in DB (OAuth users have no password hash)
        db = SessionLocal()
        try:
            db_user = db.query(User).filter(User.username == email).first()
            if not db_user:
                db_user = User(username=email, hashed_password=None)
                db.add(db_user)
                db.commit()
        finally:
            db.close()

        existing_owner = get_setting("owner_email")

        # 1. First-Time Setup: Set this Google account as the Authorized Owner
        if not existing_owner:
            set_setting("owner_email", email)
            if tokens.get("refresh_token"):
                set_setting("google_refresh_token", tokens["refresh_token"])
            if tokens.get("access_token"):
                set_setting("google_access_token", tokens["access_token"])
            set_setting("user_name", tokens.get("name") or email)
            set_setting("user_picture", tokens.get("picture") or "")

            # Issue session cookie
            jwt_token = create_access_token({"sub": email})
            redirect = RedirectResponse(url="/login?step=2", status_code=status.HTTP_302_FOUND)
            redirect.set_cookie(
                key="access_token",
                value=jwt_token,
                httponly=True,
                max_age=30 * 24 * 3600,
                samesite="lax",
                secure=is_request_secure(request)
            )
            redirect.delete_cookie(key="oauth_code_verifier")
            redirect.delete_cookie(key="oauth_state")
            return redirect

        # 2. Subsequent Login: Enforce that only the registered Owner can log in
        if email.strip().lower() != existing_owner.strip().lower():
            return RedirectResponse(
                url=f"/login?error=unauthorized_account&detail={quote(email)}",
                status_code=status.HTTP_302_FOUND
            )

        # Update tokens if provided
        if tokens.get("refresh_token"):
            set_setting("google_refresh_token", tokens["refresh_token"])
        if tokens.get("access_token"):
            set_setting("google_access_token", tokens["access_token"])
        if tokens.get("picture"):
            set_setting("user_picture", tokens["picture"])

        jwt_token = create_access_token({"sub": email})
        target_url = "/dashboard" if get_setting("setup_completed") == "true" else "/login?step=2"
        redirect = RedirectResponse(url=target_url, status_code=status.HTTP_302_FOUND)
        redirect.set_cookie(
            key="access_token",
            value=jwt_token,
            httponly=True,
            max_age=30 * 24 * 3600,
            samesite="lax",
            secure=is_request_secure(request)
        )
        redirect.delete_cookie(key="oauth_code_verifier")
        redirect.delete_cookie(key="oauth_state")
        return redirect

    except Exception as e:
        print(f"Error during Google OAuth callback: {e}")
        return RedirectResponse(url=f"/login?error=oauth_exchange_failed&detail={quote(str(e))}")

@router.post("/api/setup/provision-template")
async def provision_template(
    file: Optional[UploadFile] = File(None),
    title: Optional[str] = Form("Credit Card Payment Tracker")
):
    """
    Provisions a Google Sheet by uploading an Excel template (.xlsx)
    and converting it automatically into a native Google Sheet.
    Uses uploaded file, or falls back to bundled 'Credit Card Payment Tracker.xlsx'.
    """
    creds = get_google_credentials()
    if not creds:
        raise HTTPException(status_code=401, detail="Google authentication required. Please sign in with Google first.")

    try:
        if file and file.filename:
            content = await file.read()
            result = provision_spreadsheet_from_template(content, title=title or "Credit Card Payment Tracker", creds=creds)
        else:
            # Use bundled template
            bundled_path = "Credit Card Payment Tracker.xlsx"
            if not os.path.exists(bundled_path):
                raise HTTPException(status_code=404, detail="Bundled template 'Credit Card Payment Tracker.xlsx' not found.")
            result = provision_spreadsheet_from_template(bundled_path, title=title or "Credit Card Payment Tracker", creds=creds)

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to provision Google Sheet from template: {str(e)}")

@router.post("/api/setup/verify-and-finish")
def verify_and_finish_setup(payload: VerifySetupSchema):
    """
    Runs an automated 3-point live health check:
    1. Google Identity Token
    2. Google Sheet Read/Write permission
    3. Gmail API Statements label search
    Marks setup_completed = true if successful.
    """
    creds = get_google_credentials()
    if not creds:
        raise HTTPException(status_code=401, detail="Google account not connected.")

    owner_email = get_setting("owner_email")
    sheet_id = get_setting("spreadsheet_id")
    target_label = payload.gmail_label or get_setting("gmail_label", "Statements")

    checks = []

    # Check 1: Google Identity
    checks.append({
        "name": "Google Identity & OAuth 2.0",
        "detail": f"Authenticated as {owner_email}",
        "success": bool(owner_email)
    })

    # Check 2: Google Sheets API
    sheets_ok = False
    sheet_details = ""
    try:
        sheets_svc = get_sheets_service(creds)
        if sheet_id:
            meta = sheets_svc.spreadsheets().get(spreadsheetId=sheet_id).execute()
            tabs = [s["properties"]["title"] for s in meta.get("sheets", [])]
            sheets_ok = True
            sheet_details = f"Verified \"{meta.get('properties', {}).get('title')}\" with tabs: {', '.join(tabs[:4])}"
        else:
            sheet_details = "Spreadsheet has not been provisioned yet."
    except Exception as e:
        sheet_details = f"Sheet check error: {str(e)}"

    checks.append({
        "name": "Google Sheets API & Tracker",
        "detail": sheet_details,
        "success": sheets_ok
    })

    # Check 3: Gmail API & Label Access
    gmail_ok = False
    gmail_details = ""
    try:
        gmail_svc = get_gmail_service(creds)
        res = gmail_svc.users().messages().list(userId="me", q=f'label:{target_label}', maxResults=5).execute()
        msgs = res.get("messages", [])
        gmail_ok = True
        gmail_details = f"Label \"{target_label}\" active ({len(msgs)} recent statement emails found)"
    except Exception as e:
        gmail_details = f"Gmail search error: {str(e)}"

    checks.append({
        "name": "Gmail Ingestion API",
        "detail": gmail_details,
        "success": gmail_ok
    })

    all_passed = all(c["success"] for c in checks)
    if all_passed:
        set_setting("gmail_label", target_label)
        set_setting("setup_completed", "true")

    return {
        "success": all_passed,
        "checks": checks,
        "setup_completed": all_passed
    }
