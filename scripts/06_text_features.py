"""Extension text features (pre-specified before running the models).

1. Outlook tone — net tone of the forward-looking part of the MD&A ("公司未来发展的展望" /
   "公司关于公司未来发展的讨论与分析", which contains the risk sub-section). Taken from
   data/processed/mdna/: from the first top-level heading mentioning 未来发展 up to the next
   top-level heading that does not.
   -> tone_outlook.csv: outlook_found, outlook_words, outlook_pos, outlook_neg, outlook_tone

2. Disclosure flags from the full report text, 0/1 per firm-year:
   audit_modified  qualified / disclaimer / adverse audit opinion. "形成<X>意见的基础" is the
                   mandatory heading of a modified audit report and does not occur otherwise.
   audit_emphasis  unqualified opinion with an emphasis-of-matter paragraph.
   going_concern   the auditor's "与持续经营相关的重大不确定性" section (as a heading line;
                   the same phrase inside the standard auditor's-responsibility paragraph is ignored).
   ic_adverse      adverse internal-control audit opinion.
   audit_nonstd    any of the above.
   -> disclosure_flags.csv
"""
import re
from importlib import import_module

import pandas as pd

from common import FULLTEXT_DIR, MDNA_DIR, PROCESSED

tone = import_module("05_tone")

TOP = re.compile(r"^[一二三四五六七八九十]{1,3}、")
SUB = re.compile(r"^[（(][一二三四五六七八九十]{1,3}[）)]")
OUTLOOK = re.compile(r"未来发展|未来展望|发展展望")

FLAGS = {
    "audit_modified": re.compile(r"形成(保留|无法表示|否定)意见的基础"),
    "audit_emphasis": re.compile(r"带强调事项段|^强调事项$", re.M),
    "going_concern": re.compile(r"^([一二三四五六七八九十]{1,3}、)?\s*与持续经营相关的重大不确定性\s*$", re.M),
    "ic_adverse": re.compile(r"否定意见的内部控制审计报告|内部控制审计报告.{0,10}否定意见"),
}


def outlook_section(lines):
    for level in (TOP, SUB):
        is_head = [bool(level.match(l)) and len(l) < 40 for l in lines]
        starts = [i for i, h in enumerate(is_head) if h and OUTLOOK.search(lines[i])]
        if not starts:
            continue
        i = starts[0]
        end = next((j for j in range(i + 1, len(lines)) if is_head[j] and not OUTLOOK.search(lines[j])),
                   len(lines))
        return "\n".join(lines[i + 1:end])
    return None


def main():
    pos, neg = tone.load_lexicon()

    rows = []
    for txt in sorted(MDNA_DIR.glob("*.txt")):
        code, fy = txt.stem.split("_")
        lines = [l.strip() for l in txt.read_text(encoding="utf-8").splitlines() if l.strip()]
        sec = outlook_section(lines)
        s = tone.score_text(sec, pos, neg) if sec else dict(n_words=None, n_pos=None, n_neg=None, net_tone=None)
        rows.append(dict(code=code, fiscal_year=int(fy), outlook_found=int(sec is not None),
                         outlook_words=s["n_words"], outlook_pos=s["n_pos"], outlook_neg=s["n_neg"],
                         outlook_tone=s["net_tone"]))
    out = pd.DataFrame(rows)
    out.to_csv(PROCESSED / "tone_outlook.csv", index=False, encoding="utf-8-sig")
    print(f"outlook section found: {out['outlook_found'].sum()} / {len(out)}")
    print(out[["outlook_words", "outlook_tone"]].describe().round(3).to_string())

    rows = []
    for txt in sorted(FULLTEXT_DIR.glob("*.txt")):
        code, fy = txt.stem.split("_")
        text = txt.read_text(encoding="utf-8")
        f = {k: int(bool(p.search(text))) for k, p in FLAGS.items()}
        rows.append(dict(code=code, fiscal_year=int(fy), **f, audit_nonstd=int(any(f.values()))))
    flags = pd.DataFrame(rows)
    flags.to_csv(PROCESSED / "disclosure_flags.csv", index=False, encoding="utf-8-sig")
    print("\nflag counts over 576 firm-years:", flags.drop(columns=["code", "fiscal_year"]).sum().to_dict())


if __name__ == "__main__":
    main()
