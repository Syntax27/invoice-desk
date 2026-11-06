import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Callable

from pypdf import PdfReader
from pypdf.errors import PyPdfError


MAX_PAGES = 20
MAX_SOURCE_CHARACTERS = 30_000
CURRENCIES = frozenset({"AUD", "CAD", "CHF", "CNY", "EUR", "GBP", "HKD", "INR", "JPY", "NZD", "SGD", "USD"})
SHARED_CURRENCY_SYMBOLS = {
    "$": frozenset({"AUD", "CAD", "HKD", "NZD", "SGD", "USD"}),
    "¥": frozenset({"JPY", "CNY"}),
}

FIELD_LABELS = {
    "invoice_number": r"invoice\s*(?:number|no\.?|id|#)",
    "invoice_date": r"invoice date|date of issue|issue date|issued on",
    "total": r"invoice total|grand total|total amount|total due|amount due|total",
    "currency": r"invoice currency|currency(?: code)?",
}
LABEL_PATTERNS = {
    field: re.compile(rf"^(?:{labels})(?:\s*:\s*|\s+|(?<=#)|$)(.*)$", re.IGNORECASE)
    for field, labels in FIELD_LABELS.items()
}


@dataclass(frozen=True)
class Extraction:
    invoice_number: str | None
    invoice_date: str | None
    total: str | None
    currency: str | None
    source_text: str
    issues: tuple[str, ...]


class InvalidPdf(ValueError):
    pass


def _invoice_number(value: str) -> str:
    number = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,63}", number):
        raise ValueError("Enter an invoice number of up to 64 letters, digits, dots, slashes, hyphens or underscores. Start with a letter or digit.")
    return number


def _invoice_date(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
    raise ValueError("Enter a valid date in YYYY-MM-DD format.")


def _total(value: str) -> str:
    amount = value.strip()
    if not re.fullmatch(r"(?:[0-9]{1,12}|[0-9]{1,3}(?:,[0-9]{3}){1,3})(?:\.[0-9]{1,2})?", amount):
        raise ValueError("Enter a nonnegative amount with up to 12 whole digits and two decimal places.")
    return f"{Decimal(amount.replace(',', '')):.2f}"


def _currency(value: str) -> str:
    code = value.strip().upper()
    if code not in CURRENCIES:
        raise ValueError("Enter a supported three-letter currency code such as USD, EUR, INR or JPY.")
    return code


FIELD_VALIDATORS = {
    "invoice_number": _invoice_number,
    "invoice_date": _invoice_date,
    "total": _total,
    "currency": _currency,
}


def validate_invoice(
    invoice_number: str, invoice_date: str, total: str, currency: str
) -> tuple[dict[str, str], dict[str, str]]:
    submitted = {
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "total": total,
        "currency": currency,
    }
    fields = {}
    errors = {}
    for field, validate in FIELD_VALIDATORS.items():
        try:
            fields[field] = validate(submitted[field])
        except ValueError as error:
            errors[field] = str(error)
    return fields, errors


def _date_in_document(value: str) -> str:
    if re.fullmatch(r"[0-9]{4}[-/][0-9]{2}[-/][0-9]{2}", value):
        return _invoice_date(value.replace("/", "-"))

    numeric = re.fullmatch(r"([0-9]{1,2})[/-]([0-9]{1,2})[/-]([0-9]{4})", value)
    if numeric:
        first, second, year = map(int, numeric.groups())
        if 0 < first <= 12 and 0 < second <= 12 and first != second:
            raise ValueError("The invoice date could use either day-month or month-day order. Enter the date as YYYY-MM-DD.")
        month, day = (second, first) if first > 12 else (first, second)
        return _invoice_date(f"{year:04d}-{month:02d}-{day:02d}")

    for date_format in ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, date_format).date().isoformat()
        except ValueError:
            continue
    raise ValueError("The invoice date format could not be read. Enter the date as YYYY-MM-DD.")


def _read_source(pdf: bytes) -> tuple[str, bool]:
    if not pdf.startswith(b"%PDF-"):
        raise InvalidPdf("Choose a readable PDF file.")

    try:
        reader = PdfReader(BytesIO(pdf))
        if reader.is_encrypted:
            raise InvalidPdf("Save an unlocked copy of the PDF and upload it again.")
        if len(reader.pages) > MAX_PAGES:
            raise InvalidPdf(f"Upload a PDF with {MAX_PAGES} pages or fewer.")

        remaining = MAX_SOURCE_CHARACTERS + 1
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if pages:
                text = "\n" + text
            pages.append(text[:remaining])
            remaining -= len(pages[-1])
            if remaining == 0:
                break
    except InvalidPdf:
        raise
    except (PyPdfError, KeyError, OverflowError, TypeError, ValueError, RecursionError) as error:
        raise InvalidPdf("The PDF could not be read. Try opening it and saving a fresh copy.") from error
    source = "".join(pages)
    return source[:MAX_SOURCE_CHARACTERS].strip(), len(source) > MAX_SOURCE_CHARACTERS


def _label_values(lines: list[str], field: str) -> list[str]:
    matches = []
    for index, line in enumerate(lines):
        match = LABEL_PATTERNS[field].fullmatch(line)
        if not match:
            continue

        value = match[1]
        if not value and index + 1 < len(lines):
            next_line = lines[index + 1]
            if not any(pattern.fullmatch(next_line) for pattern in LABEL_PATTERNS.values()):
                value = next_line
        if value:
            matches.append(value)
    return matches


def _extract_field(
    values: list[str], label: str, validate: Callable[[str], str]
) -> tuple[str | None, str | None]:
    if not values:
        return None, f"Could not find the {label} in the PDF."

    normalized = set()
    try:
        for value in values:
            normalized.add(validate(value))
    except ValueError as error:
        return None, str(error)
    if len(normalized) > 1:
        return None, f"The PDF lists different {label} values. Check the source and enter the correct value."
    return normalized.pop(), None


def _split_total(value: str) -> tuple[str, list[str], str | None]:
    match = re.fullmatch(
        r"(?:([A-Za-z]{3})\s*)?([$€£¥₹])?\s*([0-9][0-9,.]*)(?:\s*([A-Za-z]{3}))?", value
    )
    if not match:
        return value, [], None

    leading, symbol, amount, trailing = match.groups()
    codes = [code for code in (leading, trailing) if code]
    symbol_code = {"€": "EUR", "£": "GBP", "₹": "INR"}.get(symbol)
    if symbol_code:
        codes.append(symbol_code)
    return amount, codes, symbol


def parse_invoice(pdf: bytes) -> Extraction:
    source_text, clipped = _read_source(pdf)
    if not source_text:
        return Extraction(None, None, None, None, "", ("The PDF has no embedded text. Enter the invoice fields manually.",))

    complete_text = source_text.rpartition("\n")[0] if clipped else source_text
    lines = [" ".join(line.split()) for line in complete_text.splitlines() if line.strip()]
    number, number_issue = _extract_field(_label_values(lines, "invoice_number"), "invoice number", _invoice_number)
    issued_on, date_issue = _extract_field(_label_values(lines, "invoice_date"), "invoice date", _date_in_document)

    currency_candidates = _label_values(lines, "currency")
    total_candidates = []
    shared_symbols = set()
    for value in _label_values(lines, "total"):
        amount, codes, symbol = _split_total(value)
        total_candidates.append(amount)
        currency_candidates.extend(codes)
        if symbol in SHARED_CURRENCY_SYMBOLS:
            shared_symbols.add(symbol)

    total, total_issue = _extract_field(total_candidates, "invoice total", _total)
    currency, currency_issue = _extract_field(currency_candidates, "currency", _currency)
    if shared_symbols and not currency_candidates:
        currency_issue = "The symbol is shared by several currencies. Enter the three-letter currency code."
    elif currency and any(currency not in SHARED_CURRENCY_SYMBOLS[symbol] for symbol in shared_symbols):
        currency = None
        currency_issue = "The currency symbol and code disagree. Check the source and enter the correct code."
    source_issue = "The extracted text exceeds the preview limit. Check the original PDF." if clipped else None
    issues = tuple(issue for issue in (number_issue, date_issue, total_issue, currency_issue, source_issue) if issue)
    return Extraction(number, issued_on, total, currency, source_text, issues)
