import re
import pdfplumber
from datetime import datetime
from parsers.base import BaseParser

MONTH_MAP = {
    "jan": "JANUARY", "feb": "FEBRUARY", "mar": "MARCH",
    "apr": "APRIL", "may": "MAY", "jun": "JUNE",
    "jul": "JULY", "aug": "AUGUST", "sep": "SEPTEMBER",
    "oct": "OCTOBER", "nov": "NOVEMBER", "dec": "DECEMBER"
}

class ENBDParser(BaseParser):
    def parse(self):
        full_text = ""
        with pdfplumber.open(self.pdf_stream) as pdf:
            for page in pdf.pages:
                full_text += (page.extract_text() or "") + "\n"

        # 1. Total Payment Due — from STATEMENT SUMMARY row
        #    Header: Previous Statement Due ... Total Payment Due (AED) Current Balance (AED)
        #    Values: 12.00 5,169.23 0.00 12.00 5,169.23 5,169.23
        total_due = 0.0
        summary_match = re.search(
            r"STATEMENT SUMMARY.*?"
            r"Total Payment Due \(AED\)[^\n]*\n"
            r"(?:[^\n]*\n)?"
            r"[\d,]+\.\d{2}\s+[\d,]+\.\d{2}\s+[\d,]+\.\d{2}\s+[\d,]+\.\d{2}\s+([\d,]+\.\d{2})",
            full_text, re.DOTALL | re.IGNORECASE
        )
        if summary_match:
            total_due = float(summary_match.group(1).replace(",", ""))
        else:
            # Fallback pattern for Total Payment Due
            fallback = re.search(
                r"Total Payment Due[^\n\d]*\(AED\)[^\d\n]*\n.*?([\d,]+\.\d{2})\s+[\d,]+\.\d{2}",
                full_text, re.DOTALL | re.IGNORECASE
            )
            if fallback:
                total_due = float(fallback.group(1).replace(",", ""))

        # 2. Statement Date / Billing Cycle
        #    Example: "Statement Date Payment Due Date Minimum Payment Due\n... 10/10/2026"
        #    or "Statement Period: 11-Sep-26 to 10-Oct-26"
        month = datetime.utcnow().strftime("%B").upper()
        year = datetime.utcnow().year

        stmt_date_match = re.search(r"Statement Date.*?(\d{2}/\d{2}/\d{4})", full_text, re.DOTALL)
        period_match = re.search(r"Statement Period:\s*.*?to\s*(\d{2})-([A-Za-z]{3})-(\d{2,4})", full_text, re.IGNORECASE)

        if stmt_date_match:
            stmt_date = datetime.strptime(stmt_date_match.group(1), "%d/%m/%Y")
            month = stmt_date.strftime("%B").upper()
            year = stmt_date.year
        elif period_match:
            month_abbr = period_match.group(2).lower()[:3]
            month = MONTH_MAP.get(month_abbr, month)
            yr_str = period_match.group(3)
            year = int(yr_str) if len(yr_str) == 4 else int("20" + yr_str)

        # 3. Transactions
        #    Format: "Transaction Date Posting Date Description Amount[CR]"
        #    Example: "02/10/2026 03/10/2026 *CLOUDFLARE SAN FRANCISCO USA 13.00 USD 49.23"
        transactions = []
        trans_pattern = re.compile(
            r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+(.+?)\s+([\d,]+\.\d{2})(CR)?\s*$",
            re.MULTILINE
        )
        for match in trans_pattern.finditer(full_text):
            tx_date, post_date, desc, amt_str, is_cr = match.groups()
            transactions.append({
                "date": tx_date,
                "description": desc.strip(),
                "amount": float(amt_str.replace(",", "")),
                "type": "CREDIT" if is_cr else "DEBIT"
            })

        return {
            "total_due": total_due,
            "month": month,
            "year": year,
            "transactions": transactions
        }
