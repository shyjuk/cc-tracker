import re
import pdfplumber
from datetime import datetime
from parsers.base import BaseParser

class CBDParser(BaseParser):
    def parse(self):
        full_text = ""
        with pdfplumber.open(self.pdf_stream) as pdf:
            for page in pdf.pages:
                full_text += (page.extract_text() or "") + "\n"

        total_due_match = re.search(r"(?:Total\s+Payment\s+Due|Total\s+Amount\s+Due)[^\d]*([\d,]+\.\d{2})", full_text, re.IGNORECASE)
        total_due = float(total_due_match.group(1).replace(",", "")) if total_due_match else 0.0

        date_match = re.search(r"(?:Statement\s+Date)\s*[:\s]*(\d{2}[-/]\d{2}[-/]\d{4})", full_text, re.IGNORECASE)
        if date_match:
            raw_d = date_match.group(1).replace("-", "/")
            stmt_date = datetime.strptime(raw_d, "%d/%m/%Y")
            month = stmt_date.strftime("%B").upper()
            year = stmt_date.year
        else:
            month = datetime.utcnow().strftime("%B").upper()
            year = datetime.utcnow().year

        return {
            "total_due": total_due,
            "month": month,
            "year": year,
            "transactions": []
        }
