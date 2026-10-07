"""Alternative tone from the DLUT emotion lexicon (大连理工大学情感词汇本体, dict/DLUT_情感词汇本体.csv).

A general-domain lexicon with polarity (1 positive, 2 negative, 0 neutral, 3 both), intensity
(1-9) and 21 emotion categories. Scores per report:
  n_words, n_pos, n_neg          token counts (polarity 1 / 2 words)
  net_tone                       intensity-weighted: (sum int_pos - sum int_neg) / (sum int_pos + sum int_neg)
  net_tone_count                 unweighted count version
  fear_share, sad_share, blame_share   words per 1,000 tokens in the 惧 (NI/NC/NG), 哀 (NB/NJ/NH/PF)
                                 and 恶 (NN/ND/NE/NL/NK) groups
Output columns n_words/n_pos/n_neg/net_tone match tone.csv so the file can replace it in the model.
  python 10_dlut_tone.py                -> tone_dlut.csv        (full report)
  python 10_dlut_tone.py --source mdna  -> tone_dlut_mdna.csv   (MD&A only)
"""
import argparse
import re
import time

import jieba
import pandas as pd

from common import DICT_DIR, FULLTEXT_DIR, MDNA_DIR, PROCESSED

WORDLIKE = re.compile(r"[一-鿿A-Za-z]")
GROUPS = {"fear": {"NI", "NC", "NG"}, "sad": {"NB", "NJ", "NH", "PF"}, "blame": {"NN", "ND", "NE", "NL", "NK"}}
SOURCES = {"fulltext": (FULLTEXT_DIR, "tone_dlut.csv"), "mdna": (MDNA_DIR, "tone_dlut_mdna.csv")}


def load_dlut():
    d = pd.read_csv(DICT_DIR / "DLUT_情感词汇本体.csv", encoding="utf-8-sig", keep_default_na=False)
    d["emotion"] = d["emotion"].str.strip().replace("", "NA")      # "NA" (anger) must not become missing
    d = d[d["polarity"].isin([1, 2])].copy()
    d["intensity"] = pd.to_numeric(d["intensity"], errors="coerce").fillna(5)
    d = d.sort_values("intensity", ascending=False).drop_duplicates("word")   # strongest sense per word
    return {w: (int(p), float(i), e) for w, p, i, e in zip(d["word"], d["polarity"], d["intensity"], d["emotion"])}


def score(text, lex):
    tokens = [t for t in jieba.lcut(text.replace("\n", "")) if WORDLIKE.search(t)]
    pos_w = neg_w = n_pos = n_neg = 0.0
    grp = {g: 0 for g in GROUPS}
    for t in tokens:
        e = lex.get(t)
        if not e:
            continue
        pol, inten, emo = e
        if pol == 1:
            n_pos += 1; pos_w += inten
        else:
            n_neg += 1; neg_w += inten
        for g, cats in GROUPS.items():
            if emo in cats:
                grp[g] += 1
    n = len(tokens)
    return dict(n_words=n, n_pos=int(n_pos), n_neg=int(n_neg),
                net_tone=(pos_w - neg_w) / (pos_w + neg_w) if pos_w + neg_w else None,
                net_tone_count=(n_pos - n_neg) / (n_pos + n_neg) if n_pos + n_neg else None,
                **{f"{g}_share": 1000 * v / n if n else None for g, v in grp.items()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=SOURCES, default="fulltext")
    text_dir, out_name = SOURCES[ap.parse_args().source]
    lex = load_dlut()
    jieba.setLogLevel(60)
    for w in lex:
        jieba.add_word(w, freq=100000)
    print(f"DLUT: {sum(v[0] == 1 for v in lex.values())} positive, {sum(v[0] == 2 for v in lex.values())} negative words")
    t0 = time.time()
    rows = [dict(code=f.stem.split("_")[0], fiscal_year=int(f.stem.split("_")[1]),
                 **score(f.read_text(encoding="utf-8"), lex)) for f in sorted(text_dir.glob("*.txt"))]
    df = pd.DataFrame(rows)
    df.to_csv(PROCESSED / out_name, index=False, encoding="utf-8-sig")
    print(f"{out_name}: {len(df)} rows in {time.time() - t0:.0f}s")
    print(df.drop(columns=["code", "fiscal_year"]).describe().round(3).loc[["mean", "min", "50%", "max"]].to_string())


if __name__ == "__main__":
    main()
