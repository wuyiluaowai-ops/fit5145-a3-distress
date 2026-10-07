"""Lead time between the annual reports and the distress event -> data/processed/event_lead_time.csv

st_date  = earliest risk-warning / restructuring announcement in the event year T
           (data/raw/sample_check.csv from 00_verify_sample.py; first_warning as fallback)
report dates come from data/raw/download_log.csv.
lead_T1_days = days from publication of the FY T-1 annual report to the event; lead_T2_days likewise.
"""
import re

import pandas as pd

from common import PROCESSED, RAW, load_sample


def main():
    chk = pd.read_csv(RAW / "sample_check.csv", dtype=str)
    log = pd.read_csv(RAW / "download_log.csv", dtype=str)

    def publish(code, fy):
        p = log[(log["code"] == code) & (log["fiscal_year"] == str(fy))]["publish_date"]
        return pd.Timestamp(p.iloc[0]) if len(p) else pd.NaT

    rows = []
    for f in load_sample().query("group == 'distress'").itertuples():
        c = chk[chk["code"] == f.code]
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", str(c["events_T"].iloc[0])) if len(c) else []
        if dates:
            st = pd.Timestamp(min(dates))
        elif len(c) and isinstance(c["first_warning"].iloc[0], str):
            st = pd.Timestamp(c["first_warning"].iloc[0])
        else:
            st = pd.NaT
        d1, d2 = publish(f.code, f.event_year - 1), publish(f.code, f.event_year - 2)
        days = lambda d: (st - d).days if pd.notna(st) and pd.notna(d) else None
        rows.append(dict(code=f.code, name=f.name, event_year=f.event_year,
                         st_date=st.date() if pd.notna(st) else None,
                         report_T1_date=d1.date() if pd.notna(d1) else None,
                         report_T2_date=d2.date() if pd.notna(d2) else None,
                         lead_T1_days=days(d1), lead_T2_days=days(d2)))
    out = pd.DataFrame(rows)
    out.to_csv(PROCESSED / "event_lead_time.csv", index=False, encoding="utf-8-sig")
    print(out.to_string(index=False))
    print("\nmedian lead (days): T-1 report", out["lead_T1_days"].median(), "| T-2 report", out["lead_T2_days"].median())
    print("T-1 report published within 7 days of the event:", int((out["lead_T1_days"] <= 7).sum()), "/", len(out))


if __name__ == "__main__":
    main()
