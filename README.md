# Financial distress prediction for Chinese new-energy firms — FIT5145 Assignment 3

Dataset, data pipeline and R Markdown for FIT5145 Assignment 3 (Runxi Tan, 36753971).
Question: does annual-report tone add to financial-ratio models in predicting financial distress
(first ST / \*ST or court-accepted restructuring) of Chinese new-energy A-share firms one year ahead?

Sample: 32 distress firms, each matched 1:2 by sub-industry with control firms (96 firms), six
fiscal years T−6 … T−1 before the event year T (576 firm-years). Features use T−6 … T−2 only.

## Quick start (R)

`Runxi_36753971_Assignment3.Rmd` reads only the four CSV files in `dataset/`. Either keep the
`dataset/` folder next to the Rmd, or set the YAML parameter to the raw GitHub URL:

```yaml
params:
  data_dir: "https://raw.githubusercontent.com/wuyiluaowai-ops/fit5145-a3-distress/main/dataset"
```

R ≥ 4.3 with tidyverse, broom, caret, glmnet, xgboost, pROC.

## Files

| Path | Content |
|---|---|
| `dataset/ratios.csv` | 576 firm-years of annual financial ratios and sample metadata 
| `dataset/tone.csv` | Annual-report net tone (whole report, Yao et al. 2021 lexicon) 
| `dataset/audit_features.csv` | Auditor's-report tone, length, procedure verbs, key-audit-matter count 
| `dataset/event_lead_time.csv` | Days from the FY T−1 / T−2 report publication to the distress event 
| `sample_list.csv` |  |English-named copy of the sample list for readers
| `A3_年报下载名单.csv` | Original sample list with Chinese column names; read by common.py |96 firms: matched pair, group, code, sub-industry, distress event, event year, fiscal-year window, notes; read by the Python pipeline
| `data/raw/download_log.csv` | URL, title, publication date and version of every annual report used 
| `data/raw/sample_check.csv` | Result of checking every firm in the sample list against cninfo announcements 
| `dict/formal_pos.txt`, `dict/formal_neg.txt` | Positive / negative word lists of the Yao et al. (2021) financial sentiment lexicon (annual-report version) |
| `scripts/` | Python pipeline (`00`–`11`, `common.py`, `cninfo.py`) and `model_functions.R` |

### Key columns

| Column | Meaning |
|---|---|
| `code` | Six-digit stock code — read as **character** to keep leading zeros |
| `group` | `distress` or `control`; the outcome is `y = 1` for distress |
| `pair_id` | Matched group (one distress firm + two controls); cross-validation folds are grouped by it |
| `flagged` | `TRUE` if distress was triggered by fraud / disclosure violations (robustness check) |
| `event_year`, `fiscal_year`, `rel_year` | `rel_year = fiscal_year − event_year` (−6 … −1) |
| `roa` | net profit / total assets |
| `gpMargin` | gross profit margin |
| `cfo_to_assets` | operating cash flow / total assets |
| `AssetTurnRatio` | revenue / average total assets |
| `currentRatio`, `cashRatio` | current assets / current liabilities; cash / current liabilities |
| `liabilityToAsset` | total liabilities / total assets |
| `ln_total_assets` | natural log of total assets (CNY) |
| `source` | `baostock` or `baostock+akshare` (gaps filled from statements) |
| `net_tone` | (positive − negative) / (positive + negative) word counts |
| `audit_tone` | Same measure computed on the auditor's report |

`sample_list.csv` columns: `pair_id`, `group` (困境 = distress, 对照 = control), `name`, `code`,
`sub_industry`, `distress_event`, `event_year` (T), `fiscal_years` (T−6 – T−1), `note` (违规 =
fraud / disclosure violation, 转型 = business transformation, 曾ST = earlier ST status),
`downloaded` (unused). Cell values are in Chinese.

Ratios are fractions (0.05 = 5 %). Other BaoStock fields in `ratios.csv` keep BaoStock's names.

## Original data sources

* Annual reports and announcements: CNINFO 巨潮资讯, <http://www.cninfo.com.cn>
* Financial indicators: BaoStock, <http://baostock.com>
* Missing items filled from Sina Finance statements via AkShare, <https://github.com/akfamily/akshare>
* Sentiment lexicon: 姚加权, 冯绪, 王赞钧, 纪荣嵘, 张维 (2021). 语调、情绪及市场影响：基于金融情绪词典. *管理科学学报*, 24(5), 26–46.
* DLUT emotion ontology (alternative lexicon, appendix only): Xu et al. (2008), <http://ir.dlut.edu.cn>

## Not included

* **Annual-report PDFs** (576 files, ≈ 2.4 GB) and text extracted from them: too large, and the
  documents are published by the firms and exchanges. All are public on cninfo.com.cn;
  `data/raw/download_log.csv` lists the exact URL of each, and `scripts/02_download_reports.py`
  downloads them again.
* **DLUT emotion ontology**: distributed by the DLUT IR Lab on application; download it from the
  lab's site and save as `dict/DLUT_情感词汇本体.csv` to run `10_dlut_tone.py`.
* **API caches** (`data/raw/financials/`): rebuilt by `01_ratios.py`.
* **Yao et al. (2021) lexicon workbook**: only the two annual-report word lists used by the
  pipeline are included; the full lexicon is published with the paper.

## Rebuilding the dataset (Python)

Python 3.13: `pip install -r requirements.txt`. Run from `scripts/` in this order; steps 00–02
need internet access (cninfo, BaoStock, AkShare), the rest run offline. Outputs go to
`data/processed/`; the four files used by the Rmd are then copied to `dataset/`.

```bash
python 00_verify_sample.py        # check the sample list against cninfo -> data/raw/sample_check.csv
python 01_ratios.py               # ratios -> ratios.csv
python 02_download_reports.py     # original-version annual-report PDFs -> data/raw/pdf, download_log.csv
python 03_mdna.py                 # MD&A text
python 04_fulltext.py             # whole-report text
python 05_tone.py                 # -> tone.csv
python 06_text_features.py        # extension features (appendix)
python 07_mdna_notes.py           # financial-report section incl. auditor's report
python 08_audit_features.py       # -> audit_features.csv
python 09_event_lead_time.py      # -> event_lead_time.csv
python 10_dlut_tone.py            # alternative lexicon (appendix; needs the DLUT file)
python 11_merged_tone.py          # merged lexicon (appendix)
```

## Design decisions

* **Original report versions.** For each fiscal year the first published version is used, not
  later corrections, so only information available at the time enters the model.
* **Feature window T−6 … T−2.** Year T−1 is excluded because its report is often published after,
  or only days before, the distress event (see `event_lead_time.csv`).
* **Industry-year adjustment by subtraction.** Ratio minus the fiscal-year sample mean; the ratio
  form (Platt & Platt) is unstable because yearly mean ROA is close to zero.
* **Pair-grouped cross-validation.** A distress firm and its controls are always in the same fold.
* **Classification threshold 0.55** for recall and confusion tables.
