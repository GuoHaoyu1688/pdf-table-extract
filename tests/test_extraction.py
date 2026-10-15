import csv
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest
from jsonschema import validate
from openpyxl import load_workbook
from pypdf import PdfReader, PdfWriter

from pdf_table_extract import extract_tables, inspect_pdf
from pdf_table_extract.core.errors import PDFError
from pdf_table_extract.core.extract import clean_table, numeric, render_page, selected_pages
from pdf_table_extract.core.templates import Templates

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
SCHEMA = json.loads((ROOT / "src/pdf_table_extract/core/result.schema.json").read_text())


def expected(name):
    with (EXAMPLES / f"{name}.expected.csv").open(newline="") as stream:
        return list(csv.reader(stream))


@pytest.mark.parametrize(
    "name,options",
    [
        ("ruled", {}),
        ("borderless", {}),
        ("multipage", {"merge_pages": True}),
        ("merged", {"fill_merged": "down", "header_rows": 2}),
    ],
)
def test_exact_acceptance_csvs(name, options, tmp_path):
    result = extract_tables(EXAMPLES / f"{name}.pdf", out=tmp_path, format="csv", **options)
    validate(result, SCHEMA)
    assert len(result["tables"]) == 1
    table = result["tables"][0]
    assert [table["headers"], *table["rows"]] == expected(name)
    assert table["quality"]["empty_cell_ratio"] == 0
    assert table["quality"]["numeric_columns"] == [1, 2]
    with (tmp_path / "table_001.csv").open(encoding="utf-8-sig", newline="") as stream:
        assert list(csv.reader(stream)) == expected(name)
    assert (tmp_path / "table_001.csv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_two_column_layout_keeps_tables_separate():
    result = extract_tables(EXAMPLES / "two-column.pdf")
    assert len(result["tables"]) == 2
    for table, name in zip(result["tables"], ["two-column-left", "two-column-right"]):
        assert [table["headers"], *table["rows"]] == expected(name)


def test_scanned_detection_does_not_claim_empty_success():
    inspected = inspect_pdf(EXAMPLES / "scanned.pdf")
    assert not inspected["pages"][0]["has_text"]
    assert inspected["pages"][0]["image_count"] == 1
    result = extract_tables(EXAMPLES / "scanned.pdf")
    assert result["tables"] == []
    assert "--ocr" in result["warnings"][0]


@pytest.mark.skipif(
    importlib.util.find_spec("rapidocr_onnxruntime") is None, reason="Optional OCR extra"
)
def test_actual_local_rapidocr_matches_scan_fixture():
    result = extract_tables(EXAMPLES / "scanned.pdf", ocr=True)
    validate(result, SCHEMA)
    table = result["tables"][0]
    assert [table["headers"], *table["rows"]] == expected("scanned")
    assert table["quality"]["ocr_mean_confidence"] > 0.85
    assert "approximate" in table["quality"]["notes"][0]


@pytest.mark.skipif(importlib.util.find_spec("camelot") is None, reason="Optional Camelot extra")
def test_actual_camelot_lattice_stream_and_compare():
    for name, flavor in [("ruled", "lattice"), ("borderless", "stream")]:
        result = extract_tables(EXAMPLES / f"{name}.pdf", engine="camelot", camelot_flavor=flavor)
        table = result["tables"][0]
        assert [table["headers"], *table["rows"]] == expected(name)
    compared = extract_tables(EXAMPLES / "ruled.pdf", compare=True)
    assert compared["comparisons"][0]["same_raw_tables"]


def test_pages_area_columns_and_merge_boundaries():
    result = extract_tables(EXAMPLES / "multipage.pdf", pages="2")
    assert result["tables"][0]["rows"] == [expected("multipage")[-1]]
    assert len(extract_tables(EXAMPLES / "multipage.pdf")["tables"]) == 2
    assert extract_tables(EXAMPLES / "multipage.pdf", merge_pages=True)["tables"][0]["pages"] == [
        1,
        2,
    ]
    selected = extract_tables(EXAMPLES / "two-column.pdf", area=[330, 80, 580, 200])
    assert len(selected["tables"]) == 1
    assert selected["tables"][0]["rows"][0][0] == "Right A"
    explicit = extract_tables(EXAMPLES / "ruled.pdf", columns=[50, 230, 330, 480])
    assert explicit["tables"][0]["rows"] == expected("ruled")[1:]


@pytest.mark.parametrize(
    "value,expected_value",
    [
        ("1,200.50", "1200.50"),
        ("(25.00)", "-25.00"),
        ("12.5%", "0.125"),
        ("0012", None),
        ("1,23", None),
        ("Example", None),
        (None, None),
        ("−4.25", "-4.25"),
    ],
)
def test_decimal_normalization_hand_calculated(value, expected_value):
    assert numeric(value) == expected_value


def test_merged_none_and_right_only_fill_absent_cells():
    result = extract_tables(EXAMPLES / "merged.pdf", header_rows=2, fill_merged="none")
    assert result["tables"][0]["rows"][1][0] is None
    raw = {
        "raw_rows": [["A", "B", "C"], ["x", None, ""], ["y", "2", "3"]],
        "bbox": [0, 0, 100, 100],
        "cells": [],
        "engine": "example",
        "notes": [],
    }
    table = clean_table(raw, 1, 1, "right", False, [])
    assert table["rows"][0] == ["x", "x", ""]


def test_xlsx_reopens_and_json_schema(tmp_path):
    result = extract_tables(EXAMPLES / "ruled.pdf", out=tmp_path, format="xlsx")
    workbook = load_workbook(tmp_path / "tables.xlsx", data_only=False)
    assert list(workbook.active.values) == [tuple(row) for row in expected("ruled")]
    assert workbook.active["C2"].data_type == "s"
    result = extract_tables(EXAMPLES / "ruled.pdf", out=tmp_path, format="json")
    validate(json.loads((tmp_path / "tables.json").read_text()), SCHEMA)
    assert result["files"]


def test_render_and_inspect_geometry():
    result = inspect_pdf(EXAMPLES / "ruled.pdf")
    assert result["pages"][0]["table_count"] == 1
    assert result["pages"][0]["width"] == 612
    assert render_page(EXAMPLES / "ruled.pdf").startswith(b"\x89PNG")


@pytest.mark.parametrize("pages", ["0", "2", "2-1", "one", "1-999999999", ""])
def test_invalid_pages_rejected(pages):
    with pytest.raises(PDFError):
        selected_pages(pages, 1)


def test_invalid_region_columns_and_encryption(tmp_path):
    for options in [{"area": [-1, 0, 100, 100]}, {"columns": [10, 10]}, {"header_rows": 0}]:
        with pytest.raises(PDFError):
            extract_tables(EXAMPLES / "ruled.pdf", **options)
    encrypted = tmp_path / "protected.pdf"
    writer = PdfWriter()
    writer.append(PdfReader(EXAMPLES / "ruled.pdf"))
    writer.encrypt("fictional-password")
    writer.write(encrypted)
    with pytest.raises(PDFError, match="encrypted"):
        inspect_pdf(encrypted)
    with pytest.raises(PDFError) as error:
        inspect_pdf(tmp_path / "missing.pdf")
    assert error.value.exit_code == 3


def test_cleanup_exclusion_and_original_numbers():
    table = extract_tables(
        EXAMPLES / "ruled.pdf", normalize_numbers=False, exclude_text=["Sample B"]
    )["tables"][0]
    assert table["rows"] == [["Sample A", "10", "1,200.50"], ["Sample C", "8", "12.5%"]]


def test_chinese_text_layer_roundtrip(tmp_path):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import Table, TableStyle

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    source = tmp_path / "unicode.pdf"
    document = Canvas(str(source))
    table = Table([["项目", "数量"], ["示例甲", "2"], ["示例乙", "3"]], colWidths=[120, 100])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                ("GRID", (0, 0), (-1, -1), 0.5, "black"),
            ]
        )
    )
    table.wrap(0, 0)
    table.drawOn(document, 50, 600)
    document.save()
    result = extract_tables(source)
    assert result["tables"][0]["headers"] == ["项目", "数量"]
    assert result["tables"][0]["rows"] == [["示例甲", "2"], ["示例乙", "3"]]


def test_invalid_render_and_exclusion_return_domain_errors(tmp_path):
    with pytest.raises(PDFError, match="PDF not found"):
        render_page(tmp_path / "missing.pdf")
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"This is not a PDF")
    with pytest.raises(PDFError, match="Cannot render PDF"):
        render_page(broken)
    with pytest.raises(PDFError):
        extract_tables(EXAMPLES / "ruled.pdf", exclude_text=["["])


@pytest.mark.parametrize(
    "options",
    [
        {"ocr": "false"},
        {"header_rows": True},
        {"area": [1, 2]},
        {"columns": ["50", 100]},
        {"pages": 1},
    ],
)
def test_invalid_template_options_do_not_persist(tmp_path, options):
    store = Templates(tmp_path)
    with pytest.raises(PDFError):
        store.save("invalid", options)
    assert store.list() == []


@pytest.mark.parametrize("format", ["json", "csv"])
def test_template_roundtrip_apply_backup(tmp_path, format):
    store = Templates(tmp_path / "data")
    store.save("example", {"pages": "1", "columns": [50, 230, 330, 480]})
    with pytest.raises(PDFError):
        store.save("example", {})
    result = store.apply("example", [str(EXAMPLES / "ruled.pdf")], str(tmp_path / "out"))
    assert result[0]["tables"][0]["rows"] == expected("ruled")[1:]
    path = tmp_path / f"templates.{format}"
    store.export(path, format)
    restored = Templates(tmp_path / "restored")
    assert restored.import_file(path) == {"imported": 1, "skipped": 0}
    assert restored.import_file(path) == {"imported": 0, "skipped": 1}
    assert restored.list() == store.list()
    with zipfile.ZipFile(store.backup()["path"]) as archive:
        assert "cache.sqlite" in archive.namelist()
    with pytest.raises(PDFError):
        store.delete("example")
    assert store.delete("example", True)["deleted"] == "example"
