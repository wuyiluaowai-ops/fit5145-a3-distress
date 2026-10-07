"""Shared paths and sample loader for the A3 pipeline."""
import re
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PDF_DIR = RAW / "pdf"
PROCESSED = ROOT / "data" / "processed"
MDNA_DIR = PROCESSED / "mdna"
FULLTEXT_DIR = PROCESSED / "fulltext"
DICT_DIR = ROOT / "dict"
SAMPLE_CSV = ROOT / "sample_list.csv"


def load_sample(path=SAMPLE_CSV):
    """One row per firm: code, name, group, pair_id, sub_industry, event_year, fy_start, fy_end, note.

    `flagged` = distress triggered by fraud / disclosure violations (note contains 违规),
    used for the robustness check.
    """
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    note = df.get("note", pd.Series("", index=df.index)).fillna("")
    years = df["fiscal_years"].str.split(r"[–\-~]", regex=True)
    out = pd.DataFrame({
        "code": df["code"].str.zfill(6),
        "name": df["name"],
        "group": df["group"].map({"困境": "distress", "对照": "control"}),
        "pair_id": df["pair_id"].astype(int),
        "sub_industry": df["sub_industry"],
        "event_year": df["event_year"].astype(int),
        "fy_start": years.str[0].astype(int),
        "fy_end": years.str[1].astype(int),
        "note": note,
        "flagged": note.str.contains("违规"),
    })
    assert (out["fy_end"] - out["fy_start"] == 5).all(), "each firm should span 6 fiscal years"
    return out


def firm_years():
    """Long table: one row per firm x fiscal year (T-6..T-1)."""
    s = load_sample()
    rows = [dict(r, fiscal_year=y) for r in s.to_dict("records")
            for y in range(r["fy_start"], r["fy_end"] + 1)]
    fy = pd.DataFrame(rows).drop(columns=["fy_start", "fy_end"])
    fy["rel_year"] = fy["fiscal_year"] - fy["event_year"]
    return fy


def exchange(code):
    return "sh" if re.match(r"^(6|9)", code) else "sz"


PAGE_NO = re.compile(r"^[\s\-—第页/\d]+$")


def pdf_lines(path):
    """(page_index, line) for every text line, with running headers/footers and page numbers removed.

    Uses pypdfium2 (the engine underneath pdfplumber). Headers/footers = short lines that appear
    on >= 30% of pages.
    """
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(path))
    try:
        pages = [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]
    finally:
        pdf.close()
    lines = [[l.strip() for l in p.replace("\r", "\n").split("\n")] for p in pages]
    counts = Counter(l for page in lines for l in set(page) if l and len(l) < 40)
    boiler = {l for l, n in counts.items() if n >= max(5, 0.3 * len(lines))}
    return [(pi, l) for pi, page in enumerate(lines) for l in page
            if l and l not in boiler and not PAGE_NO.match(l)]
