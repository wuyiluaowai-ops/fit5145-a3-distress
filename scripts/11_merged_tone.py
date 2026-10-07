"""Tone from the merged Yao (2021) + DLUT lexicon.

Merge rules (fixed before running any model):
  * polarity conflicts are resolved in favour of the finance-specific Yao lexicon;
  * weight 1.0 for words in the Yao lexicon (whether or not DLUT agrees); words that only DLUT
    lists get 0.5 (default) or, with --dlut-weight intensity, their DLUT intensity / 10
    (0.1 .. 0.9; general-language words are mostly boilerplate in annual reports);
  * presence counts; DLUT intensity enters only through the optional DLUT-only word weight
    (full intensity weighting of all words was tested in 10_dlut_tone.py).

net_tone = (sum w_pos - sum w_neg) / (sum w_pos + sum w_neg)
Output columns n_words / n_pos / n_neg / net_tone match tone.csv, so the file can replace it.
  python 11_merged_tone.py                -> tone_merged.csv        (full report)
  python 11_merged_tone.py --source mdna  -> tone_merged_mdna.csv   (MD&A only)
  --dlut-weight intensity                 -> tone_merged_w.csv / tone_merged_w_mdna.csv
"""
import argparse
import time
from importlib import import_module

import jieba
import pandas as pd

from common import DICT_DIR, FULLTEXT_DIR, MDNA_DIR, PROCESSED

yao = import_module("05_tone")
dlut = import_module("10_dlut_tone")
SOURCES = {"fulltext": (FULLTEXT_DIR, "tone_merged{}.csv"), "mdna": (MDNA_DIR, "tone_merged{}_mdna.csv")}


def merged_lexicon(dlut_weight="half"):
    pos, neg = yao.read_words(DICT_DIR / "formal_pos.txt"), yao.read_words(DICT_DIR / "formal_neg.txt")
    dl = dlut.load_dlut()                                   # word -> (polarity 1/2, intensity, emotion)
    lex = {w: (1, 1.0) for w in pos}
    lex.update({w: (2, 1.0) for w in neg})
    agree = conflict = only_dlut = 0
    for w, (pol, inten, _) in dl.items():
        if w in lex:
            agree += lex[w][0] == pol
            conflict += lex[w][0] != pol                    # Yao polarity kept
        else:
            lex[w] = (pol, 0.5 if dlut_weight == "half" else min(inten, 9) / 10)
            only_dlut += 1
    print(f"merged lexicon: {len(lex)} words | Yao {len(pos) + len(neg)} | DLUT-only {only_dlut} "
          f"| in both: {agree} agree, {conflict} conflict (Yao kept)")
    return lex


def score(text, lex):
    tokens = [t for t in jieba.lcut(text.replace("\n", "")) if yao.WORDLIKE.search(t)]
    pos_w = neg_w = 0.0
    n_pos = n_neg = 0
    for t in tokens:
        e = lex.get(t)
        if not e:
            continue
        if e[0] == 1:
            n_pos += 1; pos_w += e[1]
        else:
            n_neg += 1; neg_w += e[1]
    return dict(n_words=len(tokens), n_pos=n_pos, n_neg=n_neg, pos_w=pos_w, neg_w=neg_w,
                net_tone=(pos_w - neg_w) / (pos_w + neg_w) if pos_w + neg_w else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=SOURCES, default="fulltext")
    ap.add_argument("--dlut-weight", choices=["half", "intensity"], default="half")
    args = ap.parse_args()
    text_dir, out_name = SOURCES[args.source]
    out_name = out_name.format("" if args.dlut_weight == "half" else "_w")
    lex = merged_lexicon(args.dlut_weight)
    jieba.setLogLevel(60)
    for w in lex:
        jieba.add_word(w, freq=100000)
    t0 = time.time()
    rows = [dict(code=f.stem.split("_")[0], fiscal_year=int(f.stem.split("_")[1]),
                 **score(f.read_text(encoding="utf-8"), lex)) for f in sorted(text_dir.glob("*.txt"))]
    df = pd.DataFrame(rows)
    df.to_csv(PROCESSED / out_name, index=False, encoding="utf-8-sig")
    print(f"{out_name}: {len(df)} rows in {time.time() - t0:.0f}s")
    print(df[["n_words", "n_pos", "n_neg", "net_tone"]].describe().round(3).loc[["mean", "min", "50%", "max"]].to_string())


if __name__ == "__main__":
    main()
