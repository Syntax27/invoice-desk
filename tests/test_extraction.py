from io import BytesIO
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from pypdf import PdfWriter

from app.extraction import InvalidPdf, parse_invoice, validate_invoice


SAMPLES = Path(__file__).resolve().parents[1] / "samples"


class ExtractionTests(TestCase):
    def test_number_sign_accepts_an_optional_space_before_the_value(self):
        for label in ("Invoice #123", "Invoice # 123"):
            with self.subTest(label=label):
                source = f"{label}\nInvoice Date: 2026-10-15\nInvoice Total: USD 100"
                with patch("app.extraction._read_source", return_value=(source, False)):
                    result = parse_invoice(b"")
                self.assertEqual(result.invoice_number, "123")
                self.assertEqual(result.issues, ())

    def test_shared_symbol_requires_a_matching_explicit_currency(self):
        examples = (
            ("$100", "USD", "USD", None),
            ("CAD $100", "", "CAD", None),
            ("$100", "EUR", None, "disagree"),
            ("$100", "", None, "shared by several currencies"),
            ("¥100 CNY", "", "CNY", None),
            ("¥100", "JPY", "JPY", None),
            ("¥100 USD", "", None, "disagree"),
            ("¥100", "", None, "shared by several currencies"),
        )
        for total, code, expected_currency, expected_issue in examples:
            with self.subTest(total=total, code=code):
                source = f"Invoice Number: A100\nInvoice Date: 2026-10-15\nInvoice Total: {total}"
                if code:
                    source += f"\nCurrency: {code}"
                with patch("app.extraction._read_source", return_value=(source, False)):
                    result = parse_invoice(b"")
                self.assertEqual(result.total, "100.00")
                self.assertEqual(result.currency, expected_currency)
                if expected_issue:
                    self.assertEqual(len(result.issues), 1)
                    self.assertIn(expected_issue, result.issues[0])
                else:
                    self.assertEqual(result.issues, ())

    def test_complete_sample_layouts(self):
        samples = {
            "01-studio-invoice.pdf": ("RLS-1042", "2026-10-15", "1248.00", "USD"),
            "02-supply-invoice.pdf": ("NSS-2086", "2026-10-21", "438.50", "EUR"),
        }
        for filename, expected in samples.items():
            with self.subTest(filename=filename):
                result = parse_invoice((SAMPLES / filename).read_bytes())
                self.assertEqual((result.invoice_number, result.invoice_date, result.total, result.currency), expected)
                self.assertEqual(result.issues, ())

    def test_ambiguous_date_leaves_only_the_date_unresolved(self):
        result = parse_invoice((SAMPLES / "03-review-invoice.pdf").read_bytes())
        self.assertEqual((result.invoice_number, result.total, result.currency), ("SMB-0731", "296.00", "USD"))
        self.assertIsNone(result.invoice_date)
        self.assertEqual(len(result.issues), 1)
        self.assertIn("day-month or month-day", result.issues[0])
        self.assertIn("DD/MM/YYYY", result.source_text)

    def test_preview_cap_cannot_turn_part_of_an_amount_into_a_field(self):
        pdf = (SAMPLES / "01-studio-invoice.pdf").read_bytes()
        source_text = parse_invoice(pdf).source_text
        limit = source_text.index("1,248.00") + len("1,248")
        with patch("app.extraction.MAX_SOURCE_CHARACTERS", limit):
            result = parse_invoice(pdf)
        self.assertIsNone(result.total)
        self.assertTrue(any("preview limit" in issue for issue in result.issues))

    def test_unreadable_and_encrypted_pdfs_raise_invalid_pdf(self):
        encrypted = PdfWriter()
        encrypted.add_blank_page(width=612, height=792)
        encrypted.encrypt("example-password")
        buffer = BytesIO()
        encrypted.write(buffer)

        for document in (b"invalid", buffer.getvalue()):
            with self.assertRaises(InvalidPdf):
                parse_invoice(document)

    def test_empty_page_can_be_entered_manually(self):
        blank = PdfWriter()
        blank.add_blank_page(width=612, height=792)
        buffer = BytesIO()
        blank.write(buffer)

        result = parse_invoice(buffer.getvalue())
        self.assertEqual(result.source_text, "")
        self.assertIsNone(result.invoice_number)
        self.assertIn("no embedded text", result.issues[0])

    def test_manual_validation_normalizes_fields_and_rejects_invalid_values(self):
        fields, errors = validate_invoice(" RLS-1042 ", "2026-10-15", "1,248", "usd")
        self.assertEqual(fields, {
            "invoice_number": "RLS-1042", "invoice_date": "2026-10-15", "total": "1248.00", "currency": "USD",
        })
        self.assertEqual(errors, {})

        fields, errors = validate_invoice("=1+1", "2026-02-29", "12,34", "ZZZ")
        self.assertEqual(fields, {})
        self.assertEqual(set(errors), {"invoice_number", "invoice_date", "total", "currency"})
