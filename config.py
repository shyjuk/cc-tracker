import os
from dotenv import load_dotenv

load_dotenv()

# Google & Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
SPREADSHEET_NAME_OR_ID = os.getenv("SPREADSHEET_NAME_OR_ID", "Credit Card Payment Tracker")
SHEET_TAB_NAME = os.getenv("SHEET_TAB_NAME", "2026")
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", "statements.db")
GMAIL_LABEL = os.getenv("GMAIL_LABEL", "Statements")

# Statement Mapping Rules matching Google Sheet columns
# Headers: Emirates NBD | EI - Cashback | EI - RTA-NOL | FAB - GEMS | FAB - Blue | CBD | ADCB
STATEMENT_RULES = [
    {
        "card_code": "ENBD",
        "sheet_col": "Emirates NBD",
        "subject_query": 'TEXT "Emirates NBD"',
        "password": os.getenv("PWD_ENBD", ""),
        "parser": "enbd"
    },
    {
        "card_code": "EI_CASHBACK",
        "sheet_col": "EI - Cashback",
        "subject_query": 'TEXT "Cashback"',
        "password": os.getenv("PWD_EI_CASHBACK", ""),
        "parser": "emirates_islamic"
    },
    {
        "card_code": "EI_RTA",
        "sheet_col": "EI - RTA-NOL",
        "subject_query": 'TEXT "RTA"',
        "password": os.getenv("PWD_EI_RTA", ""),
        "parser": "emirates_islamic"
    },
    {
        "card_code": "FAB_GEMS",
        "sheet_col": "FAB - GEMS",
        "subject_query": 'TEXT "Statement of FAB Card"',
        "password": os.getenv("PWD_FAB_GEMS", ""),
        "parser": "fab"
    },
    {
        "card_code": "FAB_BLUE",
        "sheet_col": "FAB - Blue",
        "subject_query": 'TEXT "Blue"',
        "password": os.getenv("PWD_FAB_BLUE", ""),
        "parser": "fab"
    },
    {
        "card_code": "CBD",
        "sheet_col": "CBD",
        "subject_query": 'TEXT "CBD Credit Card Statement for the month"',
        "password": os.getenv("PWD_CBD", ""),
        "parser": "cbd"
    },
    {
        "card_code": "ADCB",
        "sheet_col": "ADCB",
        "subject_query": 'TEXT "ADCB"',
        "password": os.getenv("PWD_ADCB", ""),
        "parser": "adcb"
    }
]
