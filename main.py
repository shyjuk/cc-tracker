import os
import json
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from database import init_db, SessionLocal, CardStatement, CardTransaction, CardRule, SyncLog, User
from config import STATEMENT_RULES
from email_fetcher import EmailFetcher
from pdf_decryptor import decrypt_pdf_bytes
from parsers import get_parser
from sheet_updater import SheetUpdater
from auth import get_optional_user, get_current_user

# Import Routers
from routers import auth_routes, rules_routes, dashboard_routes, google_routes

SYNC_STATE = {
    "is_running": False,
    "last_run": None,
    "current_step": "Idle",
    "error": None
}

def run_sync_pipeline():
    """
    Two-phase sync pipeline:
    Phase 1: Parse and store statements in SQLite for all active card rules from database.
    Phase 2: After all cards are parsed, batch update corresponding month's fields in Google Sheets.
    """
    global SYNC_STATE
    SYNC_STATE["is_running"] = True
    SYNC_STATE["current_step"] = "Initializing Database & Connectors"
    SYNC_STATE["error"] = None

    init_db()
    db = SessionLocal()
    sheet_updater = SheetUpdater()

    sync_log = SyncLog(
        started_at=datetime.utcnow(),
        status="RUNNING"
    )
    db.add(sync_log)
    db.commit()

    statements_to_sync = []

    try:
        # Load active rules from SQLite database
        db_rules = db.query(CardRule).filter(CardRule.is_active == True).all()
        if db_rules:
            rules_to_process = [
                {
                    "card_code": r.card_code,
                    "sheet_col": r.sheet_col,
                    "subject_query": r.subject_query,
                    "password": r.password or "",
                    "parser": r.parser
                }
                for r in db_rules
            ]
        else:
            rules_to_process = STATEMENT_RULES

        print(f"\n==================================================")
        print(f"PHASE 1: Fetching & Parsing Statements For {len(rules_to_process)} Cards")
        print(f"==================================================")

        with EmailFetcher() as fetcher:
            for rule in rules_to_process:
                card_code = rule["card_code"]
                SYNC_STATE["current_step"] = f"Checking statement for {card_code}"
                print(f"\n--- Checking statements for: {card_code} ---")

                try:
                    msg_id, raw_pdf = fetcher.fetch_latest_pdf(rule["subject_query"])
                    if not raw_pdf:
                        print(f"No PDF found matching query: {rule['subject_query']}")
                        continue

                    # 1. Decrypt
                    decrypted_stream = decrypt_pdf_bytes(raw_pdf, rule["password"])

                    # 2. Parse
                    parser = get_parser(rule["parser"], decrypted_stream)
                    parsed_data = parser.parse()

                    # 3. Save to DB (Upsert: update if (card_code, month, year) exists, else insert)
                    existing_stmt = db.query(CardStatement).filter_by(
                        card_code=card_code,
                        month=parsed_data["month"],
                        year=parsed_data["year"]
                    ).first()

                    if existing_stmt:
                        existing_stmt.total_amount_due = parsed_data["total_due"]
                        existing_stmt.email_message_id = msg_id
                        existing_stmt.processed_at = datetime.utcnow()

                        # Refresh transactions
                        db.query(CardTransaction).filter_by(statement_id=existing_stmt.id).delete()
                        for tx in parsed_data["transactions"]:
                            db.add(CardTransaction(
                                statement_id=existing_stmt.id,
                                trans_date=tx["date"],
                                description=tx["description"],
                                amount=tx["amount"],
                                trans_type=tx["type"]
                            ))
                        db.commit()
                        print(f"✓ Updated existing {card_code} in SQLite: {parsed_data['month']} {parsed_data['year']} -> {parsed_data['total_due']} AED")
                    else:
                        stmt_record = CardStatement(
                            card_code=card_code,
                            month=parsed_data["month"],
                            year=parsed_data["year"],
                            total_amount_due=parsed_data["total_due"],
                            email_message_id=msg_id
                        )
                        db.add(stmt_record)
                        db.flush()

                        for tx in parsed_data["transactions"]:
                            db.add(CardTransaction(
                                statement_id=stmt_record.id,
                                trans_date=tx["date"],
                                description=tx["description"],
                                amount=tx["amount"],
                                trans_type=tx["type"]
                            ))
                        db.commit()
                        print(f"✓ Saved {card_code} to SQLite. Total: {parsed_data['total_due']} AED ({len(parsed_data['transactions'])} transactions)")

                    # Queue statement for Google Sheet sync in Phase 2
                    statements_to_sync.append({
                        "card_code": card_code,
                        "card_col_name": rule["sheet_col"],
                        "year": parsed_data["year"],
                        "month": parsed_data["month"],
                        "amount": parsed_data["total_due"]
                    })

                except Exception as card_err:
                    db.rollback()
                    print(f"Error processing {card_code}: {card_err}")

        # Phase 2: Update Google Sheets for all parsed credit cards
        SYNC_STATE["current_step"] = "Updating Google Sheets via API"
        print("\n==================================================")
        print(f"PHASE 2: Updating Google Sheets for All Cards ({len(statements_to_sync)} to update)")
        print("==================================================")
        
        sync_results = []
        if statements_to_sync:
            sync_results = sheet_updater.update_payments(statements_to_sync)
            print(f"\n✓ Successfully synchronized {len(sync_results)} card statement(s) to Google Sheets.")
        else:
            print("No statements found to sync to Google Sheets.")

        sync_log.status = "SUCCESS"
        sync_log.completed_at = datetime.utcnow()
        sync_log.cards_processed = len(statements_to_sync)
        sync_log.summary_json = json.dumps(sync_results)
        db.commit()

        SYNC_STATE["last_run"] = datetime.utcnow().isoformat()
        SYNC_STATE["current_step"] = "Completed successfully"

    except Exception as e:
        db.rollback()
        sync_log.status = "FAILED"
        sync_log.completed_at = datetime.utcnow()
        db.commit()
        SYNC_STATE["error"] = str(e)
        SYNC_STATE["current_step"] = f"Failed: {str(e)}"
        print(f"Sync pipeline encountered an error: {e}")
    finally:
        SYNC_STATE["is_running"] = False
        db.close()
        print("\n✓ Pipeline execution complete.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="Credit Card Statement Sync", lifespan=lifespan)

# Mount static files and templates
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Include Routers
app.include_router(auth_routes.router)
app.include_router(google_routes.router)
app.include_router(rules_routes.router)
app.include_router(dashboard_routes.router)

# -------------------------------------------------------------
# Frontend Page Routes
# -------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index(request: Request, user: User = Depends(get_optional_user)):
    """Landing page: redirects to /dashboard if logged in, otherwise /login."""
    from database import get_setting
    setup_done = get_setting("setup_completed") == "true"
    if user and setup_done:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user: User = Depends(get_optional_user)):
    """Renders the Login / Setup page."""
    step = request.query_params.get("step")
    from database import get_setting
    from dotenv import load_dotenv
    load_dotenv(override=True)
    setup_done = get_setting("setup_completed") == "true"
    allow_reset = os.getenv("ENABLE_SETUP_WIZARD_RESET", "false").lower() in ("true", "1", "yes")
    if user and setup_done and not (step and allow_reset):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request=request, name="login.html")

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request, user: User = Depends(get_optional_user)):
    """Renders the main Dashboard."""
    if not user and request.query_params.get("demo") != "true":
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"user": user})

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, user: User = Depends(get_optional_user)):
    """Renders the Settings and Statement Mapping Rules page."""
    if not user and request.query_params.get("demo") != "true":
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request=request, name="settings.html", context={"user": user})

# -------------------------------------------------------------
# Sync Trigger & Status Endpoints
# -------------------------------------------------------------

@app.post("/api/sync/trigger")
def trigger_sync(background_tasks: BackgroundTasks, user: User = Depends(get_current_user)):
    """Triggers the sync pipeline in background."""
    if SYNC_STATE["is_running"]:
        return {"status": "Sync already in progress", "is_running": True}

    background_tasks.add_task(run_sync_pipeline)
    return {"status": "Sync process triggered in background", "is_running": True}

@app.get("/api/sync/status")
def sync_status(user: User = Depends(get_current_user)):
    """Returns current live sync progress and status."""
    return SYNC_STATE

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
