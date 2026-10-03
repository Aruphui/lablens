import io
import re

MAX_OCR_PAGES = 8
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff")


def clean_text(s: str) -> str:
    """Repair characters that some lab PDFs encode as NUL bytes: ( ) - and :"""
    s = s.replace("\r", "")
    s = re.sub(r"(?<![\d.])((?:[01]?\d|2[0-3]))\x00([0-5]\d)(?=\s?[AaPp][Mm]\b)", r"\1:\2", s)  # 11<NUL>08 AM -> 11:08 AM
    s = re.sub(r"(?<=[\d.])[ \t]*\x00[ \t]*(?=\d)", " - ", s)   # 3.8 <NUL> 4.8 -> 3.8 - 4.8
    s = re.sub(r"\x00([^\x00\n]{1,40}?)\x00", r"(\1)", s)       # <NUL>RBC<NUL> -> (RBC)
    s = s.replace("\x00", "(")                                   # lone opener: <NUL>CBC) -> (CBC)
    s = s.replace("\x0c", "\n")
    return s


def _ocr(img) -> str:
    try:
        import pytesseract
    except ImportError:
        raise RuntimeError(
            "This file needs OCR. Install it with: pip install pytesseract pillow "
            "(and install the Tesseract app on the server)."
        )
    try:
        return pytesseract.image_to_string(img)
    except pytesseract.TesseractNotFoundError:
        raise RuntimeError("Tesseract is not installed on the server, so scanned files can't be read.")


def extract_pages(data: bytes, filename: str) -> list[str]:
    """Return one cleaned text string per page (OCR is used only for pages with no text layer)."""
    name = filename.lower()
    if name.endswith(".pdf"):
        import pdfplumber

        pages, ocr_error, ocr_used = [], None, 0
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for p in pdf.pages:
                text = p.extract_text() or ""
                if len(text.strip()) < 30 and ocr_used < MAX_OCR_PAGES and not ocr_error:
                    try:
                        text = _ocr(p.to_image(resolution=200).original)
                        ocr_used += 1
                    except RuntimeError as e:
                        ocr_error = str(e)
                pages.append(clean_text(text))
        if not any(p.strip() for p in pages) and ocr_error:
            raise RuntimeError(ocr_error)
        return pages
    if name.endswith(IMAGE_EXT):
        from PIL import Image

        return [clean_text(_ocr(Image.open(io.BytesIO(data))))]
    raise RuntimeError("Unsupported file type. Upload a PDF, PNG, JPG or WEBP.")
