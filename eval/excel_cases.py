"""Excel eval fixture + cases — measures the Excel-specialist tools on a real workbook.

`seed_xlsx(path)` writes a small Staff sheet; cases check the model answers using the
smart tools (find_rows / aggregate) instead of mis-reasoning over a raw grid.
"""
from __future__ import annotations

import openpyxl

from eval.cases import score  # reuse the same pure scorer

__all__ = ["seed_xlsx", "EXCEL_CASES", "score"]


def seed_xlsx(path: str) -> None:
    wb = openpyxl.Workbook()
    s = wb.active
    s.title = "Staff"
    s.append(["name", "dept", "salary"])
    s.append(["john", "IT", 30000])
    s.append(["mary", "HR", 28000])
    s.append(["nan", "HR", 27000])
    wb.save(path)
    wb.close()


# must_include = ALL must appear (lowercased). salary sum = 85000, headcount = 3.
EXCEL_CASES: list[dict] = [
    {"q": "ใครอยู่แผนก HR บ้าง (ดูไฟล์ staff.xlsx)", "must_include": ["mary", "nan"], "tool": "excel_find_rows"},
    {"q": "who is in the IT department in staff.xlsx?", "must_include": ["john"], "tool": "excel_find_rows"},
    {"q": "เงินเดือนรวมทุกคนใน staff.xlsx เท่าไหร่", "must_include": ["85000"], "tool": "excel_aggregate"},
    {"q": "staff.xlsx มีพนักงานกี่คน", "must_include": ["3"], "tool": "excel_aggregate"},
]
