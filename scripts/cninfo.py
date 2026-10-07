"""Thin client for the cninfo announcement search API (shared by download and verification)."""
import random
import re
import time

import requests

from common import exchange

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})

# annual-report title filters
REVISED = re.compile(r"更新后|更新版|修订|更正")
EXCLUDE = re.compile(r"摘要|英文|English|提示性|说明|问询|回复|鉴证|审计|公告|延期|半年")


def pause():
    time.sleep(random.uniform(1, 2))


def with_retry(fn, tries=3):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"  retry {i + 1}: {e}")
            time.sleep(3 * (i + 1))


def post(url, data):
    def call():
        r = session.post(url, data=data, timeout=20)
        r.raise_for_status()
        return r.json()
    return with_retry(call)


def org_id(code):
    res = post("http://www.cninfo.com.cn/new/information/topSearch/query", {"keyWord": code, "maxNum": 10})
    return next(x["orgId"] for x in res if x["code"] == code)


def announcements(code, org, start, end, category="category_ndbg_szsh", searchkey=""):
    """All announcements for one stock in [start, end]; titles stripped of highlight tags."""
    column = "sse" if exchange(code) == "sh" else "szse"
    out = []
    for page in range(1, 20):
        res = post("http://www.cninfo.com.cn/new/hisAnnouncement/query", {
            "stock": f"{code},{org}", "tabName": "fulltext", "pageSize": 30, "pageNum": page,
            "column": column, "category": category, "plate": "", "searchkey": searchkey,
            "seDate": f"{start}~{end}", "isHLtitle": "true",
        })
        out += res.get("announcements") or []
        pause()
        if not res.get("hasMore"):
            break
    for a in out:
        a["title"] = re.sub(r"<[^>]+>", "", a["announcementTitle"])
    return out


def _publish_year(a):
    return time.localtime(a["announcementTime"] / 1000).tm_year


def annual_report_candidates(anns, year):
    """Full annual reports for fiscal `year`. A title without any year (e.g. just "年度报告")
    is assigned by publication year (fiscal year + 1)."""
    def is_for_year(t, a):
        if re.search(rf"{year}\s*年?\s*年度报告", t):
            return True
        return "年度报告" in t and not re.search(r"20\d\d", t) and _publish_year(a) == year + 1
    return [a for a in anns
            if is_for_year(a["title"], a) and not EXCLUDE.search(a["title"])
            and a.get("adjunctUrl", "").lower().endswith(".pdf")]
