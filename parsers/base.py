import pdfplumber
from typing import Dict, Any

class BaseParser:
    def __init__(self, pdf_stream):
        self.pdf_stream = pdf_stream

    def parse(self) -> Dict[str, Any]:
        """
        Must return:
        {
            "total_due": float,
            "month": str ("JANUARY", "FEBRUARY", etc.),
            "year": int (e.g. 2026),
            "transactions": [{"date": ..., "description": ..., "amount": ..., "type": ...}]
        }
        """
        raise NotImplementedError
