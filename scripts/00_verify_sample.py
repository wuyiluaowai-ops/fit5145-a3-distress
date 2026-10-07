"""Verify a sample list against cninfo announcements (query only, nothing is downloaded).

For every firm:
  * risk-warning announcements (实施/实行 退市风险警示 / 其他风险警示) and court acceptance of
    restructuring (受理 ... 重整), over the firm's whole history;
  * "may be put under risk warning" notices (可能被实施 ...);
  * whether an annual report exists for every required fiscal year.

Checks
  distress: a warning / restructuring event falls in the stated event year T;
            no warning inside the feature window (fy_start .. T-1).
  control : no warning / restructuring from fy_start through T (FAIL);
            warnings after T or "may be" notices in the window are reported as NOTE.

Usage: python 00_verify_sample.py [sample.csv]   -> data/raw/sample_check.csv
"""
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from cninfo import announcements, annual_report_candidates, org_id
from common import RAW, SAMPLE_CSV, load_sample

CST = timezone(timedelta(hours=8))
IMPOSE = re.compile(r"(实施|实行)[^，,。]{0,8}(退市风险警示|其他风险警示)")
NOT_IMPOSE = re.compile(r"撤销|可能|申请|继续|变更|延期|期间|问询|回复|说明|意见|进展")
# ChiNext had no ST regime before Aug 2020: distress shows up as suspension-risk notices instead
MAYBE = re.compile(r"(可能|存在)[^，,。]{0,8}(退市风险警示|其他风险警示|暂停上市|终止上市)")
SUSPEND = re.compile(r"(暂停上市|终止上市)的(决定|公告)|股票暂停上市")
RESTRUCT = re.compile(r"受理[^，,。]{0,10}重整|重整[^，,。]{0,6}受理")


def day(a):
    return datetime.fromtimestamp(a["announcementTime"] / 1000, CST).date()


def events(anns):
    """Deduplicated (date, kind, title) for warnings / restructuring / 'may be' notices."""
    out, seen = [], set()
    for a in anns:
        t = a["title"]
        if RESTRUCT.search(t) and "预" not in t and "申请" not in t:
            kind = "restructure"
        elif IMPOSE.search(t) and not NOT_IMPOSE.search(t):
            kind = "warning"
        elif SUSPEND.search(t) and not re.search(r"风险|可能|撤销|恢复|提示", t):
            kind = "suspension"
        elif MAYBE.search(t):
            kind = "maybe"
        else:
            continue
        key = (day(a), kind)
        if key not in seen:
            seen.add(key)
            out.append(dict(date=day(a), kind=kind, title=t))
    return sorted(out, key=lambda e: e["date"])


def st_name_events(anns):
    """First announcement date per year on which the stock name carried an ST / *ST prefix.

    The stock name recorded with each announcement is the name at that time, so this catches
    warnings regardless of how the announcement title is worded.
    """
    first = {}
    for a in anns:
        name = re.sub(r"<[^>]+>", "", a.get("secName") or "")
        if re.match(r"\*?ST", name):
            d = day(a)
            if d.year not in first or d < first[d.year][0]:
                first[d.year] = (d, name)
    return [dict(date=d, kind="st_name", title=f"stock name {n}") for d, n in first.values()]


def fmt(evts):
    return "; ".join(f"{e['date']} {e['title']}" for e in evts)


def check_firm(f):
    org = org_id(f.code)
    anns = []
    for key in ("风险警示", "重整", "可能被实施", "暂停上市", "ST"):
        anns += announcements(f.code, org, "2000-01-01", datetime.now(CST).date().isoformat(),
                              category="", searchkey=key)
    ev = sorted(events(anns) + st_name_events(anns), key=lambda e: e["date"])
    hard = [e for e in ev if e["kind"] in ("warning", "restructure", "suspension", "st_name")]
    T, y0 = f.event_year, f.fy_start
    in_window = [e for e in hard if y0 <= e["date"].year <= T - 1]
    at_T = [e for e in hard if e["date"].year == T]
    maybe_window = [e for e in ev if e["kind"] == "maybe" and y0 <= e["date"].year <= T - 1]

    ar = announcements(f.code, org, f"{y0 + 1}-01-01", f"{f.fy_end + 2}-06-30")
    missing_ar = [y for y in range(y0, f.fy_end + 1) if not annual_report_candidates(ar, y)]

    issues, notes = [], []
    if f.group == "distress":
        if not at_T:
            near = [e for e in hard if T - 1 <= e["date"].year <= T + 1]
            issues.append(f"no warning/restructuring found in T={T}"
                          + (f"; nearest: {fmt(near[:2])}" if near else ""))
        if in_window:
            issues.append(f"already under warning inside window {y0}-{T - 1}: {fmt(in_window[:3])}")
        before = [e for e in hard if e["date"].year < y0]
        if before:
            notes.append(f"earlier warning before window: {fmt(before[:2])}")
    else:
        through_T = [e for e in hard if y0 <= e["date"].year <= T]
        if through_T:
            issues.append(f"control under warning/restructuring {y0}-{T}: {fmt(through_T[:3])}")
        after = [e for e in hard if e["date"].year > T]
        if after:
            notes.append(f"warning after T: {fmt(after[:2])}")
        before = [e for e in hard if e["date"].year < y0]
        if before:
            notes.append(f"warning before window: {fmt(before[:2])}")
    if maybe_window:
        notes.append(f"'may be warned' notice in window: {fmt(maybe_window[:2])}")
    if missing_ar:
        issues.append(f"no annual report found for FY {missing_ar}")

    return dict(pair_id=f.pair_id, group=f.group, code=f.code, name=f.name, event_year=T,
                window=f"{y0}-{f.fy_end}", verdict="FAIL" if issues else ("NOTE" if notes else "OK"),
                issues=" | ".join(issues), notes=" | ".join(notes),
                first_warning=str(hard[0]["date"]) if hard else "",
                events_T=fmt(at_T))


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else SAMPLE_CSV
    sample = load_sample(path)
    dup = sample[sample.duplicated("code", keep=False)]
    if len(dup):
        print("duplicate codes:\n", dup[["pair_id", "group", "code", "name"]].to_string(index=False))
    rows = []
    for f in sample.itertuples():
        try:
            r = check_firm(f)
        except Exception as e:
            r = dict(pair_id=f.pair_id, group=f.group, code=f.code, name=f.name,
                     event_year=f.event_year, verdict="ERROR", issues=repr(e))
        rows.append(r)
        print(f"[{r['verdict']}] {f.pair_id:>2} {f.group:<8} {f.code} {f.name}  {r.get('issues', '')}")
    out = pd.DataFrame(rows)
    out.to_csv(RAW / "sample_check.csv", index=False, encoding="utf-8-sig")
    print("\n", out["verdict"].value_counts().to_dict(), "-> data/raw/sample_check.csv")


if __name__ == "__main__":
    main()
