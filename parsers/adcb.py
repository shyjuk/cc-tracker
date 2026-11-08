import re
import pdfplumber
from datetime import datetime
from parsers.base import BaseParser

class ADCBParser(BaseParser):
    def parse(self):
        full_text = ""
        with pdfplumber.open(self.pdf_stream) as pdf:
            for page in pdf.pages:
                full_text += (page.extract_text() or "") + "\n"

        # 1. Total Amount Due / New Balance Outstanding
        #    ADCB PDF overlay displays "NEW BALANCE OUTSTANDING 1157.11"
        total_due = 0.0
        m_balance = re.search(r"NEW\s+BALANCE\s+OUTSTANDING\s+([\d,]+\.\d{2})", full_text, re.IGNORECASE)
        if m_balance:
            total_due = float(m_balance.group(1).replace(",", ""))
        else:
            # Fallback for standard ADCB templates
            m_alt = re.search(r"(?:Total\s+Amount\s+Due|Payment\s+Due)[^\d]*([\d,]+\.\d{2})", full_text, re.IGNORECASE)
            if m_alt:
                total_due = float(m_alt.group(1).replace(",", ""))

        # 2. Statement Date / Billing Cycle
        #    Format: "15/10/2026 NEW BALANCE OUTSTANDING" or top header "15/10/26"
        month = datetime.utcnow().strftime("%B").upper()
        year = datetime.utcnow().year

        m_date_bal = re.search(r"(\d{2}/\d{2}/\d{4})\s+NEW\s+BALANCE\s+OUTSTANDING", full_text, re.IGNORECASE)
        m_date_top = re.search(r"XXXXXXXXXXXX\d{4}\s*\n\s*(\d{2}/\d{2}/(\d{2,4}))", full_text)

        if m_date_bal:
            stmt_date = datetime.strptime(m_date_bal.group(1), "%d/%m/%Y")
            month = stmt_date.strftime("%B").upper()
            year = stmt_date.year
        elif m_date_top:
            raw = m_date_top.group(1)
            fmt = "%d/%m/%Y" if len(m_date_top.group(2)) == 4 else "%d/%m/%y"
            stmt_date = datetime.strptime(raw, fmt)
            month = stmt_date.strftime("%B").upper()
            year = stmt_date.year

        # 3. Transactions
        #    Format: "DD/MM/YYYY Description Amount [CR]"
        #    Example: "15/09/2026 WEST ZONE FRESH SUPERM DUBAI ARE 3.00"
        #             "03/10/2026 PAYMENT RECEIVED, THANK YOU 2994.00 CR"
        transactions = []
        trans_pattern = re.compile(
            r"^(\d{2}/\d{2}/\d{4})\s+(.+?)\s+([\d,]+\.\d{2})\s*(CR)?\s*$",
            re.MULTILINE
        )
        for match in trans_pattern.finditer(full_text):
            t_date, desc, amt_str, is_cr = match.groups()
            desc_clean = desc.strip()
            # Ignore balance summary rows
            if "BALANCE OUTSTANDING" in desc_clean.upper():
                continue
            transactions.append({
                "date": t_date,
                "description": desc_clean,
                "amount": float(amt_str.replace(",", "")),
                "type": "CREDIT" if is_cr else "DEBIT"
            })

        return {
            "total_due": total_due,
            "month": month,
            "year": year,
            "transactions": transactions
        }
