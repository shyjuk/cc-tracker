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

class EmiratesIslamicParser(BaseParser):
    def parse(self):
        full_text = ""
        with pdfplumber.open(self.pdf_stream) as pdf:
            for page in pdf.pages:
                full_text += (page.extract_text() or "") + "\n"

        # 1. Total Payment Due — from the summary row below the header line
        #    Header: Card Limit  Available Limit  Minimum Payment Due  Payment Due Date  Total Payment Due  ...
        #    Values: 10,000.00   9,266.28         100.00               04/11/26          733.72             ...
        total_due = 0.0
        total_match = re.search(
            r"Total Payment Due.*?Current Balance.*?\n"
            r"[\d,]+\.\d{2}\s+[\d,]+\.\d{2}\s+[\d,]+\.\d{2}\s+\S+\s+"
            r"([\d,]+\.\d{2})",
            full_text, re.IGNORECASE
        )
        if total_match:
            total_due = float(total_match.group(1).replace(",", ""))

        # 2. Statement Period — "To: 10th Oct 2026"
        month = datetime.utcnow().strftime("%B").upper()
        year = datetime.utcnow().year
        date_match = re.search(r"To:\s*\d+\w*\s+(\w+)\s+(\d{4})", full_text, re.IGNORECASE)
        if date_match:
            month_abbr = date_match.group(1).lower()[:3]
            month = MONTH_MAP.get(month_abbr, month)
            year = int(date_match.group(2))

        # 3. Transactions — "DD MMM DD MMM DESCRIPTION AMOUNT[CR]"
        transactions = []
        trans_pattern = re.compile(
            r"(\d{2})\s+(\w{3})\s+\d{2}\s+\w{3}\s+(.+?)\s+([\d,]+\.\d{2})(CR)?\s*$",
            re.MULTILINE
        )
        for match in trans_pattern.finditer(full_text):
            day, mon_abbr, desc, amt_str, is_cr = match.groups()
            # Build a date string from posting day/month and statement year
            mon_num = list(MONTH_MAP.keys()).index(mon_abbr.lower()[:3]) + 1
            t_date = f"{day}/{mon_num:02d}/{year}"
            transactions.append({
                "date": t_date,
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

