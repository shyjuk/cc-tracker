import os
import gspread
from gspread.utils import rowcol_to_a1
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from config import GOOGLE_SERVICE_ACCOUNT_FILE, SPREADSHEET_NAME_OR_ID
from database import get_setting
from google_auth import get_google_credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

class SheetUpdater:
    def __init__(self):
        # 1. Prefer user Google OAuth credentials if authenticated
        oauth_creds = get_google_credentials()
        if oauth_creds:
            self.client = gspread.authorize(oauth_creds)
        elif os.path.exists(GOOGLE_SERVICE_ACCOUNT_FILE):
            sa_creds = ServiceAccountCredentials.from_service_account_file(GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES)
            self.client = gspread.authorize(sa_creds)
        else:
            raise ValueError("No Google authentication available. Please sign in with Google or provide service_account.json.")

        # Open by ID if set, otherwise by name
        sheet_id = get_setting("spreadsheet_id")
        sheet_name = get_setting("spreadsheet_name") or SPREADSHEET_NAME_OR_ID

        if sheet_id:
            try:
                self.spreadsheet = self.client.open_by_key(sheet_id)
            except Exception:
                self.spreadsheet = self.client.open(sheet_name)
        else:
            self.spreadsheet = self.client.open(sheet_name)

        self._ws_cache = {}  # year -> worksheet

    def _get_worksheet(self, year: int):
        """Returns the worksheet tab for the given year, creating a cache entry."""
        if year not in self._ws_cache:
            tab_name = str(year)
            try:
                self._ws_cache[year] = self.spreadsheet.worksheet(tab_name)
            except gspread.exceptions.WorksheetNotFound:
                raise ValueError(
                    f"Worksheet tab '{tab_name}' not found. "
                    f"Available tabs: {[ws.title for ws in self.spreadsheet.worksheets()]}"
                )
        return self._ws_cache[year]

    def _find_cell_coordinates(self, ws, month: str, card_col_name: str):
        """Locates the (row_idx, col_idx) for a given month and card column header."""
        all_values = ws.get_all_values()
        if len(all_values) < 2:
            raise ValueError(f"Worksheet '{ws.title}' does not have adequate header rows.")

        headers = [h.strip().upper() for h in all_values[1]]
        target_col = card_col_name.strip().upper()
        if target_col not in headers:
            raise ValueError(f"Column '{card_col_name}' not found in sheet '{ws.title}' row 2. Available headers: {headers}")
        col_idx = headers.index(target_col) + 1

        target_row_idx = None
        target_month = month.strip().upper()
        for i, row in enumerate(all_values[2:], start=3):
            col_a_val = row[0].strip().upper() if row else ""
            if col_a_val == target_month:
                target_row_idx = i
                break

        if not target_row_idx:
            raise ValueError(f"Row for month '{month}' not found in tab '{ws.title}'.")

        return target_row_idx, col_idx

    def update_payment(self, year: int, month: str, card_col_name: str, amount: float):
        """
        Locates the column matching card_col_name and the row matching
        the month in Column A on the year's worksheet tab, then updates the cell.
        """
        ws = self._get_worksheet(year)
        row_idx, col_idx = self._find_cell_coordinates(ws, month, card_col_name)
        ws.update_cell(row_idx, col_idx, amount)
        a1 = rowcol_to_a1(row_idx, col_idx)
        print(f"✓ Updated Sheet: [{month} {year}] {card_col_name} -> {amount} AED (Cell {a1})")
        return a1

    def update_payments(self, payments: list[dict]) -> list[dict]:
        """
        Updates multiple card payments in Google Sheets after parsing all statements.
        Groups updates by year tab and updates cells via Google Sheets batch_update API.

        Each payment dict should contain:
        {
            "year": int,
            "month": str,
            "card_col_name": str,
            "amount": float,
            "card_code": str (optional)
        }
        """
        if not payments:
            print("No payments to update in Google Sheets.")
            return []

        # Group by year
        by_year = {}
        for p in payments:
            by_year.setdefault(p["year"], []).append(p)

        results = []
        for year, year_payments in by_year.items():
            ws = self._get_worksheet(year)
            batch_data = []

            for p in year_payments:
                card_col = p["card_col_name"]
                month = p["month"]
                amount = p["amount"]
                card_code = p.get("card_code", card_col)

                try:
                    row_idx, col_idx = self._find_cell_coordinates(ws, month, card_col)
                    cell_a1 = rowcol_to_a1(row_idx, col_idx)
                    batch_data.append({
                        "range": cell_a1,
                        "values": [[amount]],
                        "item": p,
                        "cell": cell_a1
                    })
                except Exception as e:
                    print(f"⚠️ Could not map {card_code} ({month} {year}): {e}")
                    results.append({"card_code": card_code, "status": "ERROR", "error": str(e)})

            if batch_data:
                gspread_updates = [{"range": b["range"], "values": b["values"]} for b in batch_data]
                ws.batch_update(gspread_updates)
                for b in batch_data:
                    p = b["item"]
                    card_label = p.get("card_code", p["card_col_name"])
                    print(f"✓ Google Sheet Updated: [{p['month']} {year}] {card_label} -> {p['amount']} AED (Cell {b['cell']})")
                    results.append({
                        "card_code": card_label,
                        "month": p["month"],
                        "year": year,
                        "cell": b["cell"],
                        "amount": p["amount"],
                        "status": "UPDATED"
                    })

        return results
