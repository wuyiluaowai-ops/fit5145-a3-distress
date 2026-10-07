"""Full annual-report text -> data/processed/fulltext/{code}_{fy}.txt

Whole report, with running headers/footers and page numbers removed (see common.pdf_lines).
Numbers from tables stay in the file; they are excluded later at tokenisation.
"""
import re

import pandas as pd

from common import FULLTEXT_DIR, PDF_DIR, PROCESSED, pdf_lines


def main():
    FULLTEXT_DIR.mkdir(parents=True, exist_ok=True)
    for old in FULLTEXT_DIR.glob("*.txt"):  # derived data: rebuilt from the current PDFs
        old.unlink()
    rows = []
    for pdf in sorted(PDF_DIR.glob("*.pdf")):
        code, fy = pdf.stem.split("_")
        lines = pdf_lines(pdf)
        body = "\n".join(l for _, l in lines)
        (FULLTEXT_DIR / f"{pdf.stem}.txt").write_text(body, encoding="utf-8")
        rows.append(dict(code=code, fiscal_year=int(fy), n_pages=lines[-1][0] + 1 if lines else 0,
                         n_chars=len(re.sub(r"\s", "", body))))
    df = pd.DataFrame(rows)
    df.to_csv(PROCESSED / "fulltext_check.csv", index=False, encoding="utf-8-sig")
    print(f"extracted {(df['n_chars'] > 0).sum()} / {len(df)}")
    print(df[["n_pages", "n_chars"]].describe().round(0).to_string())
    low = df[df["n_chars"] < 50000]
    print(f"\nreports under 50,000 characters ({len(low)}):")
    print(low.to_string(index=False) if len(low) else "  none")


if __name__ == "__main__":
    main()
