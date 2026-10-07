"""Financial-report section text.

The financial-report section ("第X节 财务报告": audit report, statements and notes) is cut with
the same section logic as the MD&A (03_mdna.py) and written to
  data/processed/finreport/{code}_{fy}.txt     (section alone; input to 08_audit_features.py)
  data/processed/mdna_notes/{code}_{fy}.txt    (MD&A + section; robustness tone scope,
                                                scored by `python 05_tone.py --source mdna_notes`)
"""
import re
from importlib import import_module

import pandas as pd

from common import MDNA_DIR, PDF_DIR, PROCESSED

mdna = import_module("03_mdna")
NOTES_TITLE = re.compile(r"财务(会计)?报告")
OUT = PROCESSED / "mdna_notes"
FIN = PROCESSED / "finreport"


def main():
    for d in (OUT, FIN):
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.txt"):
            old.unlink()
    rows = []
    for pdf in sorted(PDF_DIR.glob("*.pdf")):
        notes, meta = mdna.extract(pdf, NOTES_TITLE)
        md = MDNA_DIR / f"{pdf.stem}.txt"
        md_text = md.read_text(encoding="utf-8") if md.exists() else ""
        (FIN / f"{pdf.stem}.txt").write_text(notes or "", encoding="utf-8")
        (OUT / f"{pdf.stem}.txt").write_text(md_text + "\n" + (notes or ""), encoding="utf-8")
        rows.append(dict(file=pdf.stem, notes_found=int(bool(notes)),
                         notes_chars=len(re.sub(r"\s", "", notes or "")),
                         **{k: meta.get(k) for k in ("heading", "next_section", "start_page", "end_page")}))
    df = pd.DataFrame(rows)
    df.to_csv(PROCESSED / "mdna_notes_check.csv", index=False, encoding="utf-8-sig")
    print(f"financial-report section found: {df['notes_found'].sum()} / {len(df)}")
    print(df["notes_chars"].describe().round(0).to_string())
    print("next section:", df["next_section"].value_counts(dropna=False).head(6).to_dict())


if __name__ == "__main__":
    main()
