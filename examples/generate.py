"""Generate six fictional PDF acceptance fixtures and expected CSVs."""

import csv
import io
from pathlib import Path

import pypdfium2 as pdfium
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Table, TableStyle

ROOT = Path(__file__).parent
HEADER = ["Item", "Quantity", "Amount"]
ROWS = [["Sample A", "10", "1,200.50"], ["Sample B", "5", "(25.00)"], ["Sample C", "8", "12.5%"]]
NORMAL = [["Sample A", "10", "1200.50"], ["Sample B", "5", "-25.00"], ["Sample C", "8", "0.125"]]


def table(canvas, rows, x=50, top=700, widths=None, spans=None):
    grid = Table(rows, colWidths=widths or [180, 100, 150], rowHeights=32)
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#46566a")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 12),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e4ecf4")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]
    for span in spans or []:
        commands.append(("SPAN", *span))
    grid.setStyle(TableStyle(commands))
    _, height = grid.wrap(0, 0)
    grid.drawOn(canvas, x, top - height)


def canvas(name):
    return Canvas(str(ROOT / f"{name}.pdf"), pagesize=(612, 792), invariant=1)


def expected(name, rows):
    with (ROOT / f"{name}.expected.csv").open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream).writerows(rows)


def generate():
    doc = canvas("ruled")
    table(doc, [HEADER, *ROWS])
    doc.save()
    expected("ruled", [HEADER, *NORMAL])
    doc = canvas("borderless")
    doc.setFont("Helvetica", 12)
    for row_index, row in enumerate([HEADER, *ROWS]):
        for x, value in zip([60, 240, 340], row):
            doc.drawString(x, 680 - row_index * 32, value)
    doc.save()
    expected("borderless", [HEADER, *NORMAL])
    doc = canvas("multipage")
    table(doc, [HEADER, *ROWS[:2]])
    doc.showPage()
    table(doc, [HEADER, ROWS[2]])
    doc.save()
    expected("multipage", [HEADER, *NORMAL])
    doc = canvas("merged")
    rows = [
        ["Region", "Measures", ""],
        ["Name", "Quantity", "Amount"],
        ["Group A", "10", "1,200.50"],
        ["", "5", "(25.00)"],
        ["Group B", "8", "12.5%"],
    ]
    table(doc, rows, spans=[((1, 0), (2, 0)), ((0, 2), (0, 3))])
    doc.save()
    expected(
        "merged",
        [
            ["Region/Name", "Measures/Quantity", "Measures/Amount"],
            ["Group A", "10", "1200.50"],
            ["Group A", "5", "-25.00"],
            ["Group B", "8", "0.125"],
        ],
    )
    doc = canvas("two-column")
    table(doc, [["Key", "Value"], ["Left A", "1"], ["Left B", "2"]], x=40, widths=[130, 100])
    table(doc, [["Key", "Value"], ["Right A", "3"], ["Right B", "4"]], x=340, widths=[130, 100])
    doc.save()
    expected("two-column-left", [["Key", "Value"], ["Left A", "1"], ["Left B", "2"]])
    expected("two-column-right", [["Key", "Value"], ["Right A", "3"], ["Right B", "4"]])
    with pdfium.PdfDocument(ROOT / "ruled.pdf") as source:
        page = source[0]
        bitmap = page.render(scale=2.5)
        image = bitmap.to_pil().copy()
        bitmap.close()
        page.close()
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    doc = canvas("scanned")
    doc.drawImage(ImageReader(encoded), 0, 0, width=612, height=792)
    doc.save()
    expected("scanned", [HEADER, *NORMAL])


if __name__ == "__main__":
    generate()
    print("Generated 6 fictional PDFs and 7 expected CSV files")
