"""Task 4: extract the MD&A section from each annual report -> data/processed/mdna/{code}_{fy}.txt

Text is extracted with pypdfium2 (the PDF engine underneath pdfplumber; ~100x faster here).
The MD&A heading is "董事会报告" (FY2013-2014, MD&A is its first part), "经营情况讨论与分析"
(up to FY2020) or "管理层讨论与分析" (FY2021+; some FY2015 reports).
Section boundaries are lines that are exactly "第X节 <title>". A table-of-contents entry is
skipped by choosing, among all MD&A heading hits, the one that spans the most text before the
next section heading. Page headers/footers are removed as lines repeated across many pages.

Also writes data/processed/mdna_check.csv; files < 3,000 or > 60,000 characters are flagged.
"""
import re

import pandas as pd

from common import MDNA_DIR, PDF_DIR, PROCESSED, pdf_lines

# FY2013-2014 reports carry MD&A inside "董事会报告" (it opens with "一、管理层讨论与分析")
MDNA_TITLE = re.compile(r"(经营情况讨论与分析|管理层讨论与分析|董事会报告)")
SECTION = re.compile(r"^第([一二三四五六七八九十]{1,3})节\s*([^\d….·]{2,30}?)\s*$")
CN_DIGIT = {c: i for i, c in enumerate("零一二三四五六七八九")}


def cn_to_int(s):
    """Chinese section numeral (一 .. 二十九) -> int."""
    if "十" not in s:
        return CN_DIGIT[s]
    tens, _, ones = s.partition("十")
    return (CN_DIGIT[tens] if tens else 1) * 10 + (CN_DIGIT[ones] if ones else 0)
MIN_CHARS, MAX_CHARS = 3000, 60000


GLUED = re.compile(r"^(.*[。；;!！?？」”)）])\s*(第[一二三四五六七八九十]{1,3}节\s*\S{2,30})$")


def split_glued_headings(lines):
    """Some PDFs glue a section heading onto the end of the previous paragraph's last line."""
    out = []
    for page, l in lines:
        m = GLUED.match(l)
        if m:
            out += [(page, m.group(1).strip()), (page, m.group(2).strip())]
        else:
            out.append((page, l))
    return out


def extract(path, title_re=MDNA_TITLE):
    """Text of the top-level section whose heading matches title_re (default: the MD&A)."""
    lines = split_glued_headings(pdf_lines(path))
    heads = [(i, cn_to_int(m.group(1)), m.group(2))
             for i, (_, l) in enumerate(lines) if (m := SECTION.match(l))]
    best = None
    for k, (i, num, title) in enumerate(heads):
        if not title_re.search(title):
            continue
        # section N ends at heading N+1; a cross-reference line such as
        # "第十节 财务报告之八、..." inside the body is therefore not mistaken for the end
        later = heads[k + 1:]
        end = next((j for j, n, _ in later if n == num + 1),
                   next((j for j, _, t in later if t != title), len(lines)))
        span = sum(len(l) for _, l in lines[i + 1:end])
        if best is None or span > best[2]:
            best = (i, end, span, title)
    if best is None:
        return None, {}
    i, end, _, title = best
    body = "\n".join(l for _, l in lines[i + 1:end])
    next_title = next((t for j, _, t in heads if j == end), "")
    return body, dict(heading=title, next_section=next_title,
                      start_page=lines[i][0] + 1, end_page=lines[end - 1][0] + 1)


def main():
    MDNA_DIR.mkdir(parents=True, exist_ok=True)
    for old in MDNA_DIR.glob("*.txt"):  # derived data: rebuilt from the current PDFs
        old.unlink()
    rows = []
    for pdf in sorted(PDF_DIR.glob("*.pdf")):
        code, fy = pdf.stem.split("_")
        try:
            body, meta = extract(pdf)
        except Exception as e:
            body, meta = None, {"error": repr(e)}
        n = len(re.sub(r"\s", "", body)) if body else 0
        if body:
            (MDNA_DIR / f"{pdf.stem}.txt").write_text(body, encoding="utf-8")
        flag = "not_found" if not body else "too_short" if n < MIN_CHARS else "too_long" if n > MAX_CHARS else ""
        rows.append(dict(code=code, fiscal_year=int(fy), n_chars=n, flag=flag, **meta))
    df = pd.DataFrame(rows)
    df.to_csv(PROCESSED / "mdna_check.csv", index=False, encoding="utf-8-sig")
    print(f"extracted {(df['n_chars'] > 0).sum()} / {len(df)}")
    print("chars: median", int(df["n_chars"].median()), "min", df["n_chars"].min(), "max", df["n_chars"].max())
    print("next section:", df["next_section"].value_counts().to_dict())
    flagged = df[df["flag"] != ""]
    print(f"\nflagged for manual review ({len(flagged)}):")
    print(flagged.to_string(index=False) if len(flagged) else "  none")


if __name__ == "__main__":
    main()
