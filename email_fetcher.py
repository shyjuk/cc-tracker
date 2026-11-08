import os
import io
import base64
import email
import imaplib
from typing import Optional, Tuple
from config import GMAIL_LABEL
from database import get_setting
from google_auth import get_google_credentials, get_gmail_service

class EmailFetcher:
    """
    Unified Email Fetcher supporting:
    1. Gmail REST API (using OAuth 2.0 credentials - fast, HTTPS, token-based)
    2. IMAP SSL (using IMAP_USER / IMAP_PASSWORD fallback)
    """
    def __init__(self, mailbox=None):
        self.mailbox = mailbox or get_setting("gmail_label") or os.getenv("GMAIL_LABEL", "Statements")
        self.host = os.getenv("IMAP_HOST", "imap.gmail.com")
        self.user = os.getenv("IMAP_USER")
        self.password = os.getenv("IMAP_PASSWORD")
        self.mail = None
        self.gmail_service = None
        self.use_gmail_api = False

    def __enter__(self):
        # 1. Try Gmail REST API if OAuth credentials are saved
        creds = get_google_credentials()
        if creds:
            try:
                self.gmail_service = get_gmail_service(creds)
                self.use_gmail_api = True
                return self
            except Exception as e:
                print(f"Gmail REST API init failed, falling back to IMAP: {e}")

        # 2. Fallback to IMAP SSL
        if self.user and self.password:
            self.mail = imaplib.IMAP4_SSL(self.host)
            self.mail.login(self.user, self.password)
            self.mail.select(self.mailbox)
            self.use_gmail_api = False
            return self

        raise ValueError("Neither Google OAuth credentials nor IMAP credentials are configured.")

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.mail:
            try:
                self.mail.close()
                self.mail.logout()
            except Exception:
                pass

    def _format_search_query(self, query: str) -> str:
        """Ensures query is properly formatted for IMAP search."""
        q = query.strip()
        if q.startswith("(") and q.endswith(")"):
            return q
        imap_keywords = ("SUBJECT", "FROM", "TO", "TEXT", "BODY", "OR", "AND", "NOT", "ALL")
        if any(q.upper().startswith(kw) for kw in imap_keywords):
            return f"({q})"
        clean = q.strip('"\'')
        return f'(TEXT "{clean}")'

    def _extract_pdf_from_gmail_payload(self, message_id: str, payload: dict) -> Tuple[Optional[str], Optional[bytes]]:
        """Recursively traverses a Gmail API message payload looking for PDF attachments."""
        parts = payload.get("parts", [])
        if not parts and payload.get("body", {}).get("attachmentId"):
            parts = [payload]

        for part in parts:
            filename = part.get("filename", "")
            if filename.lower().endswith(".pdf"):
                body = part.get("body", {})
                if "data" in body:
                    return filename, base64.urlsafe_b64decode(body["data"])
                elif "attachmentId" in body:
                    att = self.gmail_service.users().messages().attachments().get(
                        userId="me", messageId=message_id, id=body["attachmentId"]
                    ).execute()
                    return filename, base64.urlsafe_b64decode(att["data"])

            if "parts" in part:
                res_fn, res_data = self._extract_pdf_from_gmail_payload(message_id, part)
                if res_data is not None:
                    return res_fn, res_data

        return None, None

    def fetch_latest_pdf(self, search_query: str) -> Tuple[Optional[str], Optional[bytes]]:
        """Searches messages and extracts the latest PDF attachment."""
        if self.use_gmail_api:
            # Gmail REST API search
            # Clean search query for Gmail syntax (e.g. TEXT "Cashback" -> "Cashback")
            clean_term = search_query
            if clean_term.upper().startswith("TEXT "):
                clean_term = clean_term[5:].strip()
            elif clean_term.upper().startswith("SUBJECT "):
                clean_term = f'subject:{clean_term[8:].strip()}'
            clean_term = clean_term.strip("()")

            gmail_q = f'label:"{self.mailbox}" {clean_term}'.strip()
            res = self.gmail_service.users().messages().list(
                userId="me", q=gmail_q, maxResults=5
            ).execute()
            messages = res.get("messages", [])
            if not messages:
                # Also try without quotes on label in case it's a standard system label
                res = self.gmail_service.users().messages().list(
                    userId="me", q=f'label:{self.mailbox} {clean_term}', maxResults=5
                ).execute()
                messages = res.get("messages", [])

            if not messages:
                return None, None

            # Get the most recent matching message
            latest_id = messages[0]["id"]
            msg = self.gmail_service.users().messages().get(userId="me", id=latest_id).execute()
            msg_id = msg.get("id")

            fn, pdf_bytes = self._extract_pdf_from_gmail_payload(latest_id, msg.get("payload", {}))
            return msg_id, pdf_bytes

        else:
            # IMAP SSL search
            formatted_query = self._format_search_query(search_query)
            status, messages = self.mail.search(None, formatted_query)
            if status != "OK" or not messages[0]:
                return None, None

            msg_ids = messages[0].split()
            latest_id = msg_ids[-1]

            status, msg_data = self.mail.fetch(latest_id, "(RFC822)")
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    msg_id = msg.get("Message-ID", str(latest_id.decode()))

                    for part in msg.walk():
                        content_disp = str(part.get("Content-Disposition"))
                        content_type = part.get_content_type()
                        if "attachment" in content_disp or content_type == "application/pdf":
                            filename = part.get_filename()
                            if filename and filename.lower().endswith(".pdf"):
                                return msg_id, part.get_payload(decode=True)

            return None, None
