"""Task 3: download annual report PDFs from cninfo.

Version rule (agreed with the user): take the ORIGINAL disclosure of each fiscal year, i.e. the
earliest full report. cninfo labels superseded originals "（已取消）" and keeps them downloadable,
so those are NOT excluded; revised versions (更新后/修订/更正) are only used if no original exists.

Output: data/raw/pdf/{code}_{fiscal_year}.pdf and data/raw/download_log.csv.
Re-runnable: files already listed in the log with the same URL are skipped.
"""
from datetime import datetime, timedelta, timezone

import pandas as pd

from cninfo import (REVISED, announcements, annual_report_candidates as candidates, org_id,
                    pause, session, with_retry)
from common import PDF_DIR, RAW, load_sample

LOG_CSV = RAW / "download_log.csv"
CST = timezone(timedelta(hours=8))


def download(url, path):
    def call():
        tmp = path.with_suffix(".part")
        with session.get(url, timeout=90, stream=True) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
        with open(tmp, "rb") as f:
            if f.read(4) != b"%PDF":
                raise ValueError("response is not a PDF")
        tmp.replace(path)
    with_retry(call)


def main():
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    old = pd.read_csv(LOG_CSV, dtype=str) if LOG_CSV.exists() else pd.DataFrame(columns=["file", "url"])
    done = dict(zip(old["file"], old["url"]))
    log = []

    for firm in load_sample().itertuples():
        code, y0, y1 = firm.code, firm.fy_start, firm.fy_end
        org = org_id(firm.code)
        anns = announcements(code, org, f"{y0 + 1}-01-01", f"{y1 + 2}-06-30")
        for year in range(y0, y1 + 1):
            cands = candidates(anns, year)
            if not any(not REVISED.search(a["title"]) for a in cands):
                # fallback: keyword search without category filter
                extra = announcements(code, org, f"{year + 1}-01-01", f"{year + 2}-06-30",
                                      category="", searchkey=f"{year}年年度报告")
                seen = {a["adjunctUrl"] for a in cands}
                cands += [a for a in candidates(extra, year) if a["adjunctUrl"] not in seen]
            base = dict(code=code, name=firm.name, fiscal_year=year)
            if not cands:
                print(f"[MISSING] {code} {firm.name} {year}")
                log.append(dict(base, status="missing"))
                continue
            originals = [a for a in cands if not REVISED.search(a["title"])]
            pick = min(originals or cands, key=lambda a: a["announcementTime"])
            url = "http://static.cninfo.com.cn/" + pick["adjunctUrl"]
            fname = f"{code}_{year}.pdf"
            path = PDF_DIR / fname
            status = "skipped"
            if not path.exists() or done.get(fname) != url:
                download(url, path)
                status = "downloaded"
                pause()
            pub = datetime.fromtimestamp(pick["announcementTime"] / 1000, CST).date().isoformat()
            log.append(dict(base, status=status, file=fname, url=url, title=pick["title"],
                            publish_date=pub, n_versions=len(cands),
                            version="original" if originals else "revised_only",
                            size_kb=round(path.stat().st_size / 1024),
                            download_time=datetime.now(CST).isoformat(timespec="seconds")))
            print(f"[{status}] {fname} {firm.name} {pub} {pick['title']}")

    df = pd.DataFrame(log)
    df.to_csv(LOG_CSV, index=False, encoding="utf-8-sig")
    ok = df["status"].ne("missing").sum()
    print(f"done: {ok} / {len(df)}; revised_only: {(df.get('version') == 'revised_only').sum()}")


if __name__ == "__main__":
    main()
