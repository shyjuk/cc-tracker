import io
from pypdf import PdfReader, PdfWriter

def decrypt_pdf_bytes(encrypted_pdf_bytes: bytes, password: str) -> io.BytesIO:
    """Decrypts a PDF stream using the provided password and returns an in-memory unlocked PDF."""
    input_stream = io.BytesIO(encrypted_pdf_bytes)
    reader = PdfReader(input_stream)

    if reader.is_encrypted:
        success = reader.decrypt(password)
        if success == 0:
            raise ValueError("Decryption failed. Incorrect password provided.")

    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    output_stream = io.BytesIO()
    writer.write(output_stream)
    output_stream.seek(0)
    return output_stream
