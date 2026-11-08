# Credit Card Statement Analyzer & Google Sheet Synchronizer

Automated pipeline and Web GUI to download monthly password-protected UAE credit card statements from email, extract amounts and itemized transactions, store records in SQLite, and synchronize totals into a formatted Google Sheet matrix.

## Features
- **Web GUI Dashboard:** Interactive web interface with login, first-time setup prompt, KPI cards, monthly payment matrix mirroring Google Sheets, and statement transaction inspector.
- **Statement Mapping Rules in Settings:** Dynamic CRUD interface in the browser to add, edit, toggle, or delete bank mapping rules, complete with a live "Test Query in Gmail" button.
- **Email Ingestion:** Automatically queries and downloads statements from Gmail / IMAP using configurable mailbox labels (`Statements`).
- **In-Memory Decryption:** Decrypts password-protected bank PDFs with `pypdf` in-memory without writing unencrypted files to disk.
- **Bank Parsers:** Preconfigured extractors for Emirates NBD, Emirates Islamic (Cashback & RTA), FAB (GEMS & Blue), CBD, and ADCB.
- **SQLite Storage:** Maintains statements and itemized transactions with duplicate detection via email message IDs.
- **Two-Phase Google Sheets Matrix Sync:** Parses all statements first, then updates corresponding month fields via Google Sheets API `batch_update`.
- **Connection Diagnostics:** In-app real-time connection testers for both Gmail IMAP and Google Sheets API.

## Quick Start

1. **Activate virtual environment and install dependencies:**
   ```bash
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure `.env`:**
   Ensure `IMAP_USER`, `IMAP_PASSWORD`, `GMAIL_LABEL=Statements`, and `SPREADSHEET_NAME_OR_ID` are configured.

3. **Launch the Web GUI:**
   ```bash
   python main.py
   # or
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

4. **Access the Web App:**
   - Open your browser to **`http://localhost:8000`**
   - **First-time setup:** If no admin user exists, you will automatically be prompted with the **First-Time Administrator Setup** card to choose your username and password.
   - Once set up, log in to access the **Dashboard** and **Settings**.
