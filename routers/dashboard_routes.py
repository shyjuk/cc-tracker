import os
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import CardStatement, CardTransaction, CardRule, SyncLog, User
from auth import get_db, get_current_user
import imaplib

router = APIRouter(prefix="/api", tags=["Dashboard & Diagnostics"])

MONTH_NAMES = [
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
    "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"
]

@router.get("/dashboard/stats")
def get_dashboard_stats(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Returns summary KPIs for the dashboard."""
    now = datetime.utcnow()
    current_month = now.strftime("%B").upper()
    current_year = now.year

    # Current month total
    stmts_current_month = db.query(CardStatement).filter(
        CardStatement.year == current_year,
        CardStatement.month == current_month
    ).all()
    current_month_total = sum(s.total_amount_due for s in stmts_current_month)

    # Active rules count
    active_rules_count = db.query(CardRule).filter(CardRule.is_active == True).count()
    total_statements_count = db.query(CardStatement).count()

    # Last sync log
    last_sync = db.query(SyncLog).order_by(SyncLog.id.desc()).first()
    last_sync_info = None
    if last_sync:
        last_sync_info = {
            "id": last_sync.id,
            "status": last_sync.status,
            "started_at": last_sync.started_at.isoformat() if last_sync.started_at else None,
            "completed_at": last_sync.completed_at.isoformat() if last_sync.completed_at else None,
            "cards_processed": last_sync.cards_processed or 0
        }

    return {
        "current_period": f"{current_month} {current_year}",
        "current_month_total": round(current_month_total, 2),
        "active_rules_count": active_rules_count,
        "total_statements_count": total_statements_count,
        "last_sync": last_sync_info
    }

@router.get("/dashboard/matrix")
def get_payment_matrix(year: int = 2026, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Returns the monthly payment matrix matching the Google Sheet format:
    Rows: Months (JANUARY - DECEMBER)
    Columns: Active cards + Total
    """
    rules = db.query(CardRule).filter(CardRule.is_active == True).order_by(CardRule.id.asc()).all()
    columns = [{"code": r.card_code, "name": r.sheet_col} for r in rules]

    # Query all statements for the specified year
    statements = db.query(CardStatement).filter(CardStatement.year == year).all()
    
    # Map: (month, card_code) -> amount
    data_map = {}
    for s in statements:
        data_map[(s.month.upper(), s.card_code)] = s.total_amount_due

    # If DB doesn't have earlier months, also check if Google Sheet has historical values
    sheet_data_map = {}
    try:
        from sheet_updater import SheetUpdater
        updater = SheetUpdater()
        ws = updater._get_worksheet(year)
        sheet_rows = ws.get_all_values()
        if len(sheet_rows) >= 2:
            headers = [h.strip().upper() for h in sheet_rows[1]]
            for row in sheet_rows[2:14]:
                if row and row[0].strip():
                    m_name = row[0].strip().upper()
                    for r in rules:
                        col_name = r.sheet_col.strip().upper()
                        if col_name in headers:
                            c_idx = headers.index(col_name)
                            if c_idx < len(row) and row[c_idx].strip():
                                clean_val = row[c_idx].replace(",", "").strip()
                                try:
                                    sheet_data_map[(m_name, r.card_code)] = float(clean_val)
                                except ValueError:
                                    pass
    except Exception as e:
        # Graceful fallback to SQLite DB values only
        pass

    rows = []
    column_totals = {r.card_code: 0.0 for r in rules}
    grand_total = 0.0

    for month in MONTH_NAMES:
        row_values = {}
        row_total = 0.0
        for r in rules:
            # Prefer DB value, fall back to Google Sheet value if available
            amt = data_map.get((month, r.card_code))
            if amt is None:
                amt = sheet_data_map.get((month, r.card_code))

            if amt is not None:
                row_values[r.card_code] = round(amt, 2)
                row_total += amt
                column_totals[r.card_code] += amt
            else:
                row_values[r.card_code] = None

        grand_total += row_total
        rows.append({
            "month": month,
            "values": row_values,
            "total": round(row_total, 2) if row_total > 0 else 0.0
        })

    return {
        "year": year,
        "columns": columns,
        "rows": rows,
        "column_totals": {k: round(v, 2) for k, v in column_totals.items()},
        "grand_total": round(grand_total, 2)
    }

@router.get("/statements")
def list_statements(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Lists statements with transaction counts, sorted by latest first."""
    statements = db.query(CardStatement).order_by(CardStatement.processed_at.desc()).all()
    results = []
    for s in statements:
        tx_count = db.query(CardTransaction).filter(CardTransaction.statement_id == s.id).count()
        results.append({
            "id": s.id,
            "card_code": s.card_code,
            "month": s.month,
            "year": s.year,
            "total_due": s.total_amount_due,
            "transactions_count": tx_count,
            "processed_at": s.processed_at.strftime("%d %b %Y, %H:%M") if s.processed_at else None,
            "email_message_id": s.email_message_id
        })
    return results

@router.get("/statements/{statement_id}/transactions")
def get_statement_transactions(statement_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Returns the transactions for a specific statement."""
    statement = db.query(CardStatement).filter(CardStatement.id == statement_id).first()
    if not statement:
        raise HTTPException(status_code=404, detail="Statement not found.")

    transactions = db.query(CardTransaction).filter(CardTransaction.statement_id == statement_id).all()
    return {
        "statement": {
            "id": statement.id,
            "card_code": statement.card_code,
            "month": statement.month,
            "year": statement.year,
            "total_due": statement.total_amount_due
        },
        "transactions": [
            {
                "id": t.id,
                "date": t.trans_date,
                "description": t.description,
                "amount": t.amount,
                "type": t.trans_type
            }
            for t in transactions
        ]
    }

@router.post("/settings/test-imap")
def test_imap_connection(current_user: User = Depends(get_current_user)):
    """Tests Gmail connection (via OAuth Gmail API or IMAP fallback) and Statements label access."""
    from google_auth import get_google_credentials, get_gmail_service
    from database import get_setting

    target_label = get_setting("gmail_label", os.getenv("GMAIL_LABEL", "Statements"))
    creds = get_google_credentials()
    if creds:
        try:
            gmail_svc = get_gmail_service(creds)
            res = gmail_svc.users().messages().list(userId="me", q=f'label:{target_label}', maxResults=10).execute()
            msgs = res.get("messages", [])
            owner = get_setting("owner_email", "Google Account")
            return {
                "success": True,
                "message": f"Connected via Gmail REST API ({owner})! Found {len(msgs)} recent message(s) under label '{target_label}'."
            }
        except Exception as ge:
            print(f"Gmail API test error: {ge}")

    # Fallback to IMAP
    host = os.getenv("IMAP_HOST", "imap.gmail.com")
    user = os.getenv("IMAP_USER", "")
    password = os.getenv("IMAP_PASSWORD", "")

    if not user or not password:
        return {"success": False, "error": "Neither Google OAuth nor IMAP credentials are configured."}

    try:
        mail = imaplib.IMAP4_SSL(host)
        mail.login(user, password)
        status, count = mail.select(target_label)
        msg_count = count[0].decode() if count else "0"
        mail.close()
        mail.logout()
        return {
            "success": True,
            "message": f"Successfully connected to IMAP ({user})! Found {msg_count} messages in label '{target_label}'."
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.post("/settings/test-sheets")
def test_sheets_connection(current_user: User = Depends(get_current_user)):
    """Tests Google Sheets API authentication and spreadsheet access."""
    try:
        from sheet_updater import SheetUpdater
        updater = SheetUpdater()
        spreadsheet = updater.spreadsheet
        tabs = [ws.title for ws in spreadsheet.worksheets()]
        return {
            "success": True,
            "message": f"Connected to Google Sheets: \"{spreadsheet.title}\"",
            "available_tabs": tabs
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
