import re
import pdfplumber
from datetime import datetime
from parsers.base import BaseParser

class FABParser(BaseParser):
    def parse(self):
        full_text = ""
        with pdfplumber.open(self.pdf_stream) as pdf:
            for page in pdf.pages:
                full_text += (page.extract_text() or "") + "\n"

        # 1. Total Payment Due — from Summary Details row
        #    Header: Previous Balance + Purchases/Debits + Cash Advances + Finance Charges - Payments/Credits Total Payment Due
        #    Values: 2,332.26 3,768.27 0.00 0.00 3,833.00 2,267.53
        total_due = 0.0
        summary_match = re.search(
            r"Previous Balance.*?Total Payment Due\s*\n"
            r"[\d,]+\.\d{2}\s+[\d,]+\.\d{2}\s+[\d,]+\.\d{2}\s+[\d,]+\.\d{2}\s+[\d,]+\.\d{2}\s+([\d,]+\.\d{2})",
            full_text, re.IGNORECASE
        )
        if summary_match:
            total_due = float(summary_match.group(1).replace(",", ""))
        else:
            # Fallback patterns for Total Payment Due / Total Outstanding
            m_alt = re.search(r"Total Payment Due[^\n\d]*\n.*?([\d,]+\.\d{2})\s*$", full_text, re.MULTILINE)
            if not m_alt:
                m_alt = re.search(r"(?:Total\s+Amount\s+Due|Payment\s+Due|Total\s+Outstanding)[^\d]*([\d,]+\.\d{2})", full_text, re.IGNORECASE)
            if m_alt:
                total_due = float(m_alt.group(1).replace(",", ""))

        # 2. Statement Date / Billing Cycle
        #    Header: Statement Date Payment Due Date
        #    Values: 22-09-2026 17-10-2026
        month = datetime.utcnow().strftime("%B").upper()
        year = datetime.utcnow().year

        m_date = re.search(r"Statement Date[^\n]*Payment Due Date\s*\n.*?(\d{2}[-/]\d{2}[-/]\d{4})", full_text, re.IGNORECASE)
        if not m_date:
            m_date = re.search(r"Statement Date\s*[:\s]*(\d{2}[-/]\d{2}[-/]\d{4})", full_text, re.IGNORECASE)

        if m_date:
            raw_d = m_date.group(1).replace("/", "-")
            stmt_date = datetime.strptime(raw_d, "%d-%m-%Y")
            month = stmt_date.strftime("%B").upper()
            year = stmt_date.year

        # 3. Transactions
        #    Format: "Transaction Date Posting Date Description Currency OrigAmount Debit/CreditAmount"
        #    Example: "22-08-2026 23-08-2026 REEL ENTERTAINMENT LLC DUBAI ARE AED 42.00 42.00"
        #             "01-09-2026 01-09-2026 PAYMENT RECEIVED - THANK YOU AED 2,333.00 2,333.00"
        transactions = []
        trans_pattern = re.compile(
            r"^(\d{2}-\d{2}-\d{4})\s+(\d{2}-\d{2}-\d{4})\s+(.+?)\s+[A-Z]{3}\s+[\d,]+\.\d{2}\s+([\d,]+\.\d{2})\s*$",
            re.MULTILINE
        )
        for match in trans_pattern.finditer(full_text):
            tx_date, post_date, desc, amt_str = match.groups()
            desc_clean = desc.strip()
            is_credit = any(k in desc_clean.upper() for k in ["PAYMENT", "CREDIT", "REFUND", "REVERSAL"])
            transactions.append({
                "date": tx_date.replace("-", "/"),
                "description": desc_clean,
                "amount": float(amt_str.replace(",", "")),
                "type": "CREDIT" if is_credit else "DEBIT"
            })

        return {
            "total_due": total_due,
            "month": month,
            "year": year,
            "transactions": transactions
        }
