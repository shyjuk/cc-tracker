# Credit Card Statement Analyzer & Tracker

[![License: MIT](https://img.shields.io/badge/License-MIT-emerald.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-teal.svg)](https://fastapi.tiangolo.com)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

A modern, self-hosted web application and pipeline to automatically ingest password-protected credit card statement PDFs from Gmail, extract monthly balances and itemized transactions, store history in SQLite or PostgreSQL, and synchronize totals to a Google Sheets financial tracker matrix.

---

## ✨ Features

- **Automated Gmail Statement Fetcher:** Directly connects to Gmail via OAuth 2.0 REST API (or IMAP SSL fallback) to search for credit card statements matching bank sender or subject queries under a specific label (`Statements`).
- **In-Memory PDF Decryption:** Decrypts password-protected bank PDFs with `pypdf` in-memory — no unencrypted files are saved to disk.
- **Built-in UAE Bank Parsers:**
  - **Emirates NBD** (ENBD)
  - **Emirates Islamic** (Cashback & RTA-NOL)
  - **First Abu Dhabi Bank** (FAB GEMS & Blue)
  - **Commercial Bank of Dubai** (CBD)
  - **Abu Dhabi Commercial Bank** (ADCB)
  - Extensible architecture to add any bank parser in minutes.
- **3-Step First-Time Setup Wizard:**
  1. Google Cloud Console helpers with drag-and-drop `client_secret.json` upload and Google SSO.
  2. Automatic Google Sheet provisioning from bundled/custom Excel `.xlsx` templates.
  3. 3-point live health check verifying Identity, Drive/Sheets read-write, and Gmail label access.
- **Minimal Permissions:** Uses Google Drive `drive.file` and `gmail.readonly` scopes only — zero access to your other Google Drive files or broad spreadsheets.
- **Interactive Web Dashboard:** Dark-theme UI built with Tailwind CSS and Alpine.js showing:
  - Monthly balance matrix mirroring Google Sheets
  - Statement transaction inspector with debit/credit badges
  - Real-time sync trigger with live progress indicator
  - Statement mapping rules CRUD management and in-app Gmail query tester.
- **Cloud & Self-Hosted Ready:** Out of the box support for local deployment, Docker, and **FastAPI Cloud** (`fastapicloud.com`).

---

## 🚀 Quick Start

### 1. Clone the repository
```bash
git clone https://github.com/shyjuk/cc-tracker.git
cd cc-tracker
```

### 2. Create virtual environment & install dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure environment variables
Copy the example environment file:
```bash
cp .env.example .env
```
Generate a secure 32-byte secret key:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```
Paste it into `.env` as `SECRET_KEY=...` and set your card statement PDF passwords (`PWD_ENBD`, etc.).

### 4. Run the application
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
Open **http://localhost:8000** in your browser.

- On first launch, follow the **3-Step Setup Wizard** to connect your Google Account and provision your Google Sheet tracker.
- Once completed, the app transitions directly to your dashboard.

---

## 🔒 Security & Privacy

- **Single-User Ownership:** The first Google account to authenticate is recorded as the owner. Subsequent logins by any other Google account are rejected.
- **PKCE & CSRF Protection:** All OAuth authorization URLs generate unique cryptographic state tokens and PKCE `code_verifier` pairs.
- **Minimum Scopes:**
  - `https://www.googleapis.com/auth/gmail.readonly` (read statements only)
  - `https://www.googleapis.com/auth/drive.file` (only files created or opened by this app)
- **Local Isolation:** Statement PDFs are parsed in volatile memory and never exposed over unauthenticated endpoints.

---

## ⚙️ Environment Variables Reference

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | 32+ character key for signing session tokens (required) | — |
| `DATABASE_URL` | PostgreSQL or external DB URL (optional, falls back to SQLite) | `sqlite:///statements.db` |
| `GMAIL_LABEL` | Gmail mailbox label where statement emails are routed | `Statements` |
| `GOOGLE_CLIENT_ID` | OAuth 2.0 Web Client ID (can also be uploaded in Wizard) | — |
| `GOOGLE_CLIENT_SECRET` | OAuth 2.0 Web Client Secret (can also be uploaded in Wizard) | — |
| `GOOGLE_REDIRECT_URI` | Explicit OAuth callback URL | Dynamic (`localhost` / `127.0.0.1` / reverse-proxy) |
| `ENABLE_SETUP_WIZARD_RESET` | Allow re-running the setup wizard from the login page | `false` |
| `PWD_<CARD_CODE>` | PDF statement password for each card issuer | — |

---

## 🛠️ Adding a Custom Bank Parser

All parsers inherit from `BaseStatementParser` in `parsers/base.py`:

```python
from parsers.base import BaseStatementParser

class MyBankParser(BaseStatementParser):
    def parse(self) -> dict:
        text = self.extract_text()
        # Extract total_due, month, year, transactions
        return {
            "month": "OCTOBER",
            "year": 2026,
            "total_due": 1250.00,
            "transactions": [...]
        }
```
Register your parser in `parsers/__init__.py` and configure the matching card code in **Settings → Statement Mapping Rules**.

---

## 📄 License

This project is open-source software licensed under the [MIT License](LICENSE).
Feel free to use, modify, and distribute it for personal or commercial projects.
