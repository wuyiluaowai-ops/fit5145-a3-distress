"""Auditor's report features -> data/processed/audit_features.csv

Input: data/processed/finreport/ (07_mdna_notes.py). The audit report is the text from the start
of the financial-report section to the "财务报表" heading (or the first balance-sheet heading).

  audit_found, audit_words, audit_pos, audit_neg, audit_tone   lexicon tone of the audit report
  kam_found, kam_count, kam_words                                key audit matters (CSA 1504,
      mandatory for all listed firms from FY2018): number of distinct matter headings in the
      "关键审计事项" section and the section's length in words
  proc_n, proc_per_k                     count of audit-procedure verbs (获取/评价/检查/复核/测试/
      函证/询问/...) in the audit report, and per 1,000 words: a direct measure of how much the
      auditor describes doing beyond the template

The audit-report tone was found post hoc to add to the ratio model; the KAM measures test the
suspected mechanism (tone rises with the amount of procedural text in the matters section).
"""
import re
from importlib import import_module

import pandas as pd

from common import PROCESSED

tone = import_module("05_tone")
FIN = PROCESSED / "finreport"

STATEMENTS = re.compile(r"\n\s*(?:[一二三四五六七八九十]+、)?\s*财务报表\s*\n|\n\s*(?:合并)?资产负债表\s*\n")
KAM_START = re.compile(r"\n\s*(?:[一二三四五六七八九十]+、|\d+[、.．])?\s*关键审计事项[^\n]{0,30}\n")
KAM_END = re.compile(r"\n\s*(?:[一二三四五六七八九十]+、|\d+[、.．])?\s*(?:其他信息|管理层和治理层对财务报表的责任)\s*\n")
# numbered heading with a title made of Chinese characters / letters only (no digits, no sentence punctuation)
ITEM = re.compile(r"^(?P<style>（[一二三四五六七八九十]+）|\([一二三四五六七八九十]+\)|[一二三四五六七八九十]+、|\d{1,2}[、.．])"
                  r"\s*(?P<title>[一-鿿A-Za-z及和与的、（）()]{2,25})$")
SUBHEAD = re.compile(r"事项描述|审计应对|应对措施|如何应对|审计中的应对|审计程序")
PROC_VERBS = re.compile(r"获取|评价|检查|复核|测试|函证|询问|了解|观察|重新计算|分析|核对|抽样|访谈|比较|检验|评估")
PROCEDURE = re.compile(r"检查|获取|评价|了解|测试|复核|询问|函证|抽样|观察|重新计算|核对|核实|分析|执行|实施|审阅|访谈|比较|比对|针对|我们")


def style_key(s):
    return "arabic" if s[0].isdigit() else ("paren" if s[0] in "（(" else "chinese")


def audit_report(text):
    m = STATEMENTS.search(text)
    rep = text[:m.start()] if m else ""
    return rep if 400 <= len(rep) <= 30000 else ""


def kam_section(rep):
    s = KAM_START.search(rep)
    if not s:
        return None
    e = KAM_END.search(rep, s.end())
    return rep[s.end():e.start() if e else len(rep)]


def kam_count(sec):
    """Distinct matter titles per numbering style; the summary list and the detailed headings
    each enumerate every matter once, so the count is the maximum over styles."""
    by_style = {}
    for line in sec.splitlines():
        m = ITEM.match(line.strip())
        if not m or SUBHEAD.search(m["title"]) or PROCEDURE.search(m["title"]):
            continue
        by_style.setdefault(style_key(m["style"]), set()).add(re.sub(r"[（）()、]", "", m["title"]))
    if by_style:
        return max(len(v) for v in by_style.values())
    n = len(re.findall(r"审计中如何应对|如何应对该事项|审计中的应对|审计应对|执行的(?:主要)?审计程序", sec))
    return n or None


def main():
    pos, neg = tone.load_lexicon()
    rows = []
    for txt in sorted(FIN.glob("*.txt")):
        code, fy = txt.stem.split("_")
        rep = audit_report(txt.read_text(encoding="utf-8"))
        r = dict(code=code, fiscal_year=int(fy), audit_found=int(bool(rep)))
        if rep:
            s = tone.score_text(rep, pos, neg)
            r.update(audit_words=s["n_words"], audit_pos=s["n_pos"], audit_neg=s["n_neg"], audit_tone=s["net_tone"])
            n_proc = len(PROC_VERBS.findall(rep))
            r.update(proc_n=n_proc, proc_per_k=1000 * n_proc / s["n_words"] if s["n_words"] else None)
            sec = kam_section(rep)
            r.update(kam_found=int(sec is not None),
                     kam_count=kam_count(sec) if sec else None,
                     kam_words=tone.score_text(sec, pos, neg)["n_words"] if sec else None)
        rows.append(r)
    df = pd.DataFrame(rows)
    df.to_csv(PROCESSED / "audit_features.csv", index=False, encoding="utf-8-sig")
    print(f"audit report found: {df['audit_found'].sum()} / {len(df)};  KAM section: {int(df['kam_found'].sum())}")
    print("KAM section share by fiscal year:",
          df.groupby("fiscal_year")["kam_found"].mean().round(2).to_dict())
    print("kam_count distribution:", df["kam_count"].value_counts(dropna=False).sort_index().to_dict())
    print(df[["audit_words", "audit_tone", "kam_words", "proc_n"]].describe().round(3).loc[["mean", "min", "50%", "max"]].to_string())


if __name__ == "__main__":
    main()
