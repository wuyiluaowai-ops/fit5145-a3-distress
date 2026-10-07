"""Task 2: annual financial ratios -> data/processed/ratios.csv

Primary source: BaoStock quarterly indicators with quarter=4 (annual-report basis).
Total assets and statement-level items come from AkShare (Sina statements); AkShare also
fills firm-years / fields BaoStock lacks. The `source` column records where ratios came from.

Raw pulls are cached in data/raw/financials/; pass --refresh to re-download.
"""
import sys
import time

import baostock as bs
import numpy as np
import pandas as pd
import akshare as ak

from common import PROCESSED, RAW, exchange, firm_years, load_sample

CACHE = RAW / "financials"
BS_CACHE = CACHE / "baostock_q4.csv"
SINA_CACHE = CACHE / "sina_statements.csv"

# BaoStock query -> fields kept (redundant DuPont duplicates of roeAvg / AssetTurnRatio dropped)
BS_FIELDS = {
    "query_profit_data": ["roeAvg", "npMargin", "gpMargin", "netProfit", "MBRevenue"],
    "query_operation_data": ["NRTurnRatio", "INVTurnRatio", "CATurnRatio", "AssetTurnRatio"],
    "query_growth_data": ["YOYEquity", "YOYAsset", "YOYNI", "YOYPNI"],
    "query_balance_data": ["currentRatio", "quickRatio", "cashRatio", "YOYLiability",
                           "liabilityToAsset", "assetToEquity"],
    "query_cash_flow_data": ["CAToAsset", "tangibleAssetToAsset", "ebitToInterest",
                             "CFOToOR", "CFOToNP"],
    "query_dupont_data": ["dupontAssetStoEquity", "dupontPnitoni", "dupontTaxBurden",
                          "dupontIntburden", "dupontEbittogr"],
}
BS_COLS = [c for cols in BS_FIELDS.values() for c in cols]

SINA_ITEMS = {
    "资产负债表": {"total_assets": "资产总计", "total_liab": "负债合计", "cur_assets": "流动资产合计",
                "cur_liab": "流动负债合计", "equity": "所有者权益(或股东权益)合计"},
    "利润表": {"revenue": "营业总收入", "op_cost": "营业成本", "net_profit_s": "净利润",
            "parent_np": "归属于母公司所有者的净利润"},
    "现金流量表": {"cfo": "经营活动产生的现金流量净额"},
}


def fetch_baostock(fy):
    pairs = fy[["code", "fiscal_year"]].drop_duplicates()
    # one extra early year so growth fallbacks have a base
    extra = pairs.groupby("code")["fiscal_year"].min().sub(1).reset_index()
    pairs = pd.concat([pairs, extra]).drop_duplicates()
    rows = []
    bs.login()
    try:
        for i, (code, year) in enumerate(pairs.itertuples(index=False)):
            rec = {"code": code, "fiscal_year": year}
            for fn, cols in BS_FIELDS.items():
                rs = getattr(bs, fn)(code=f"{exchange(code)}.{code}", year=int(year), quarter=4)
                d = rs.get_data() if rs.error_code == "0" else pd.DataFrame()
                if len(d):
                    rec.update({c: d.iloc[0][c] for c in cols})
                    rec.setdefault("pubDate", d.iloc[0]["pubDate"])
            rows.append(rec)
            if i % 25 == 0:
                print(f"  baostock {i}/{len(pairs)}")
    finally:
        bs.logout()
    return pd.DataFrame(rows)


def fetch_sina(codes):
    frames = []
    for code in codes:
        per_code = None
        for sheet, items in SINA_ITEMS.items():
            for attempt in range(3):
                try:
                    d = ak.stock_financial_report_sina(stock=f"{exchange(code)}{code}", symbol=sheet)
                    break
                except Exception as e:
                    print(f"  sina retry {code} {sheet}: {e}")
                    time.sleep(3 * (attempt + 1))
            else:
                continue
            d = d[d["报告日"].astype(str).str.endswith("1231")]
            d = d.drop_duplicates("报告日")  # keep first row per date
            part = pd.DataFrame({"fiscal_year": d["报告日"].astype(str).str[:4].astype(int)})
            for new, old in items.items():
                part[new] = pd.to_numeric(d[old], errors="coerce").values if old in d else np.nan
            per_code = part if per_code is None else per_code.merge(part, on="fiscal_year", how="outer")
            time.sleep(1)
        if per_code is not None:
            per_code.insert(0, "code", code)
            frames.append(per_code)
        print(f"  sina {code} done")
    return pd.concat(frames, ignore_index=True)


def sina_ratios(s):
    """Map Sina statement items onto BaoStock field names (used only to fill gaps)."""
    s = s.sort_values(["code", "fiscal_year"]).copy()
    g = s.groupby("code")
    prev_ta, prev_eq = g["total_assets"].shift(), g["equity"].shift()
    prev_np, prev_tl = g["net_profit_s"].shift(), g["total_liab"].shift()
    avg_eq = (s["equity"] + prev_eq) / 2
    return pd.DataFrame({
        "code": s["code"], "fiscal_year": s["fiscal_year"],
        "roeAvg": s["parent_np"] / avg_eq,
        "npMargin": s["net_profit_s"] / s["revenue"],
        "gpMargin": (s["revenue"] - s["op_cost"]) / s["revenue"],
        "netProfit": s["net_profit_s"],
        "AssetTurnRatio": s["revenue"] / ((s["total_assets"] + prev_ta) / 2),
        "YOYEquity": s["equity"] / prev_eq - 1,
        "YOYAsset": s["total_assets"] / prev_ta - 1,
        "YOYNI": (s["net_profit_s"] - prev_np) / prev_np.abs(),
        "YOYLiability": s["total_liab"] / prev_tl - 1,
        "currentRatio": s["cur_assets"] / s["cur_liab"],
        "liabilityToAsset": s["total_liab"] / s["total_assets"],
        "assetToEquity": s["total_assets"] / s["equity"],
        "CAToAsset": s["cur_assets"] / s["total_assets"],
        "CFOToOR": s["cfo"] / s["revenue"],
        "CFOToNP": s["cfo"] / s["net_profit_s"],
    })


def main():
    refresh = "--refresh" in sys.argv
    CACHE.mkdir(parents=True, exist_ok=True)
    fy = firm_years()

    if refresh or not BS_CACHE.exists():
        print("pulling BaoStock ...")
        fetch_baostock(fy).to_csv(BS_CACHE, index=False, encoding="utf-8-sig")
    if refresh or not SINA_CACHE.exists():
        print("pulling AkShare (Sina statements) ...")
        fetch_sina(load_sample()["code"]).to_csv(SINA_CACHE, index=False, encoding="utf-8-sig")

    bsd = pd.read_csv(BS_CACHE, dtype={"code": str})
    bsd["code"] = bsd["code"].str.zfill(6)
    for c in BS_COLS:
        bsd[c] = pd.to_numeric(bsd[c], errors="coerce") if c in bsd else np.nan
    sina = pd.read_csv(SINA_CACHE, dtype={"code": str})
    sina["code"] = sina["code"].str.zfill(6)
    fill = sina_ratios(sina)

    df = fy.merge(bsd[["code", "fiscal_year"] + BS_COLS], on=["code", "fiscal_year"], how="left")
    had_bs = df[BS_COLS].notna().any(axis=1)

    # fill BaoStock gaps field by field from AkShare; also replace BaoStock values that are off
    # by a factor of ~100 against the statement-based value (BaoStock returns liabilityToAsset
    # divided by 100 for FY2024 and some FY2025 rows)
    df = df.merge(fill, on=["code", "fiscal_year"], how="left", suffixes=("", "_ak"))
    filled_any = pd.Series(False, index=df.index)
    scale_fixes = {}
    for c in fill.columns.drop(["code", "fiscal_year"]):
        ak = df[f"{c}_ak"]
        gap = df[c].isna() & ak.notna()
        ratio = (df[c] / ak).abs()
        bad = df[c].notna() & ak.notna() & (ratio.between(0.005, 0.02) | ratio.between(50, 200))
        df.loc[gap | bad, c] = ak[gap | bad]
        filled_any |= gap | bad
        if bad.any():
            scale_fixes[c] = int(bad.sum())
        df = df.drop(columns=f"{c}_ak")
    print("BaoStock scale errors replaced from statements:", scale_fixes or "none")
    df["source"] = np.select([had_bs & ~filled_any, had_bs & filled_any, ~had_bs & filled_any],
                             ["baostock", "baostock+akshare", "akshare"], "none")

    # statement-level variables (always AkShare/Sina)
    st = sina[["code", "fiscal_year", "total_assets", "cfo", "revenue"]]
    df = df.merge(st, on=["code", "fiscal_year"], how="left")
    df["roa"] = df["netProfit"] / df["total_assets"]
    df["cfo_to_assets"] = df["cfo"] / df["total_assets"]
    df["ln_total_assets"] = np.log(df["total_assets"].where(df["total_assets"] > 0))

    lead = ["code", "name", "group", "pair_id", "flagged", "event_year", "fiscal_year", "rel_year"]
    ratio_cols = BS_COLS + ["roa", "cfo_to_assets", "total_assets", "ln_total_assets"]
    df = df[lead + ratio_cols + ["source"]].sort_values(["pair_id", "group", "code", "fiscal_year"])
    PROCESSED.mkdir(parents=True, exist_ok=True)
    df.to_csv(PROCESSED / "ratios.csv", index=False, encoding="utf-8-sig")

    # missing-value report
    miss = df.melt(id_vars=["code", "name", "fiscal_year"], value_vars=ratio_cols)
    miss = miss[miss["value"].isna()].groupby(["code", "name", "fiscal_year"])["variable"] \
        .agg(lambda v: ";".join(v)).reset_index(name="missing_fields")
    miss.to_csv(PROCESSED / "ratios_missing.csv", index=False, encoding="utf-8-sig")

    print(f"\nratios.csv: {len(df)} rows (expected {len(fy)})")
    print("source:", df["source"].value_counts().to_dict())
    print("missing share by field (non-zero):")
    share = df[ratio_cols].isna().mean().sort_values(ascending=False)
    print(share[share > 0].round(3).to_string())
    print(f"\nfirm-years with any missing field: {len(miss)} -> ratios_missing.csv")
    delisted = df[df["code"].isin(["002610", "300116", "002665"])]
    print("\ndelisted firms (爱康科技 / 保力新 / 首航高科):")
    print(delisted[["code", "name", "fiscal_year", "roa", "liabilityToAsset", "CFOToOR",
                    "total_assets", "source"]].to_string(index=False))


if __name__ == "__main__":
    main()
