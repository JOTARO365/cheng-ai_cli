"""Tests for Excel tools (ai/excel_tools.py) — offline, on a tmp workspace."""
from __future__ import annotations

import openpyxl
import pytest

from ai.excel_tools import EXCEL_WRITE_TOOLS, make_excel_dispatcher


@pytest.fixture()
def ws(tmp_path):
    wb = openpyxl.Workbook()
    s = wb.active
    s.title = "Data"
    s.append(["name", "age"])
    s.append(["john", 30])
    wb.save(tmp_path / "book.xlsx")
    wb.close()
    return tmp_path


def test_list_and_read(ws):
    d = make_excel_dispatcher(ws)
    assert d("excel_list_sheets", {"path": "book.xlsx"})["sheets"] == ["Data"]
    r = d("excel_read", {"path": "book.xlsx"})
    assert r["sheet"] == "Data"
    assert r["rows"][0] == ["name", "age"]
    assert r["rows"][1] == ["john", 30]


def test_write_append_create(ws):
    d = make_excel_dispatcher(ws)
    assert d("excel_write_cell", {"path": "book.xlsx", "sheet": "Data", "cell": "C1",
                                  "value": "city"})["status"] == "written"
    assert d("excel_append_row", {"path": "book.xlsx", "sheet": "Data",
                                  "values": ["mary", 25, "bkk"]})["status"] == "appended"
    assert d("excel_create", {"path": "new.xlsx", "sheet": "S1"})["status"] == "created"
    assert (ws / "new.xlsx").exists()
    rows = d("excel_read", {"path": "book.xlsx", "sheet": "Data"})["rows"]
    assert rows[0] == ["name", "age", "city"]
    assert any("mary" in [str(c) for c in row] for row in rows)


def test_create_existing_errors(ws):
    assert "exists" in make_excel_dispatcher(ws)("excel_create", {"path": "book.xlsx"})["error"]


def test_sheet_not_found(ws):
    assert "not found" in make_excel_dispatcher(ws)(
        "excel_read", {"path": "book.xlsx", "sheet": "Nope"})["error"]


def test_sandbox_escape(ws):
    assert "escapes workspace" in make_excel_dispatcher(ws)(
        "excel_read", {"path": "../x.xlsx"}).get("error", "")


def test_write_tools_set():
    assert EXCEL_WRITE_TOOLS == {"excel_write_cell", "excel_append_row", "excel_create"}
