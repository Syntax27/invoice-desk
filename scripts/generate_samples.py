from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas


SAMPLES = Path(__file__).resolve().parents[1] / "samples"
INK = "#252B35"
MUTED = "#525C6A"
RULE = HexColor("#C8CDD3")
LEFT = 54
RIGHT = 558


def text(
    canvas: Canvas, x: int, y: int, value: str, *, font: str = "Helvetica",
    size: int = 11, color: str = INK, right: bool = False,
) -> None:
    canvas.setFont(font, size)
    canvas.setFillColor(HexColor(color))
    draw = canvas.drawRightString if right else canvas.drawString
    draw(x, y, value)


def rule(canvas: Canvas, y: int) -> None:
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.65)
    canvas.line(LEFT, y, RIGHT, y)


def new_invoice(filename: str, seller: str) -> Canvas:
    canvas = Canvas(str(SAMPLES / filename), pagesize=letter, invariant=1)
    canvas.setTitle(f"{seller} sample invoice")
    canvas.setAuthor("Invoice Desk demo")
    canvas.setSubject("Synthetic invoice for software testing")
    return canvas


def items(canvas: Canvas, y: int, rows: tuple[tuple[str, str, str, str], ...]) -> None:
    columns = (LEFT, 363, 460, RIGHT)
    for index, (x, heading) in enumerate(zip(columns, ("Description", "Qty", "Unit price", "Line total"))):
        text(canvas, x, y, heading, font="Helvetica-Bold", size=9, color=MUTED, right=index > 0)
    rule(canvas, y - 10)

    for row in rows:
        y -= 31
        for index, (x, value) in enumerate(zip(columns, row)):
            text(canvas, x, y, value, right=index > 0)
        rule(canvas, y - 11)


def finish(canvas: Canvas, note: str = "") -> None:
    if note:
        text(canvas, LEFT, 145, note, size=10, color=MUTED)
    rule(canvas, 95)
    text(canvas, LEFT, 76, "Synthetic sample for software testing. No payment is due.", size=9, color=MUTED)
    canvas.showPage()
    canvas.save()


def studio() -> None:
    seller = "Rivet Letterpress Studio"
    canvas = new_invoice("01-studio-invoice.pdf", seller)
    text(canvas, LEFT, 733, "Invoice", font="Times-Bold", size=38)
    text(canvas, RIGHT, 741, "Synthetic sample 01", size=10, color=MUTED, right=True)
    text(canvas, LEFT, 707, seller, font="Helvetica-Bold", size=13)
    rule(canvas, 689)
    text(canvas, LEFT, 662, "Bill to", font="Helvetica-Bold", size=9, color=MUTED)
    text(canvas, LEFT, 641, "Fieldglass Bookroom")
    text(canvas, LEFT, 625, "Autumn workshop series", size=10, color=MUTED)
    text(canvas, RIGHT, 662, "Invoice Number: RLS-1042", right=True)
    text(canvas, RIGHT, 642, "Invoice Date: 2026-10-15", right=True)

    items(canvas, 557, (
        ("Workshop stationery packs", "8", "95.00", "760.00"),
        ("Letterpress plates", "4", "122.00", "488.00"),
    ))
    text(canvas, RIGHT, 447, "Invoice Total: USD 1,248.00", font="Helvetica-Bold", size=14, right=True)
    finish(canvas)


def supply() -> None:
    seller = "North Spur Supply"
    canvas = new_invoice("02-supply-invoice.pdf", seller)
    text(canvas, LEFT, 734, seller, font="Helvetica-Bold", size=24)
    text(canvas, RIGHT, 737, "Invoice", font="Helvetica-Bold", size=17, right=True)
    text(canvas, RIGHT, 716, "Synthetic sample 02", size=10, color=MUTED, right=True)
    rule(canvas, 691)

    text(canvas, LEFT, 661, "Invoice ID", font="Helvetica-Bold", size=9, color=MUTED)
    text(canvas, LEFT, 643, "NSS-2086")
    text(canvas, 214, 661, "Issued On", font="Helvetica-Bold", size=9, color=MUTED)
    text(canvas, 214, 643, "21 October 2026")
    text(canvas, 375, 661, "Ship to", font="Helvetica-Bold", size=9, color=MUTED)
    text(canvas, 375, 643, "Alderwick Cabinet Works")

    items(canvas, 563, (
        ("Brass corner brackets, box of 12", "5", "54.70", "273.50"),
        ("Slotted steel fasteners, box of 50", "3", "55.00", "165.00"),
    ))
    text(canvas, RIGHT, 458, "Grand Total", font="Helvetica-Bold", size=9, color=MUTED, right=True)
    text(canvas, RIGHT, 436, "438.50 EUR", font="Helvetica-Bold", size=17, right=True)
    finish(canvas)


def review() -> None:
    seller = "Sable Mill Bindery"
    canvas = new_invoice("03-review-invoice.pdf", seller)
    text(canvas, LEFT, 733, "Invoice", font="Times-Bold", size=38)
    text(canvas, RIGHT, 741, "Synthetic sample 03", size=10, color=MUTED, right=True)
    text(canvas, LEFT, 707, seller, font="Helvetica-Bold", size=13)
    rule(canvas, 689)
    text(canvas, LEFT, 662, "Bill to", font="Helvetica-Bold", size=9, color=MUTED)
    text(canvas, LEFT, 641, "Millrun Archive")
    text(canvas, RIGHT, 662, "Invoice No.: SMB-0731", right=True)
    text(canvas, RIGHT, 642, "Invoice Date: 04/05/2026", right=True)

    items(canvas, 557, (
        ("Cloth-bound archive albums", "4", "74.00", "296.00"),
    ))
    text(canvas, RIGHT, 478, "Invoice Total: USD 296.00", font="Helvetica-Bold", size=14, right=True)
    finish(canvas, "Billing office date format: DD/MM/YYYY.")


if __name__ == "__main__":
    SAMPLES.mkdir(exist_ok=True)
    studio()
    supply()
    review()
