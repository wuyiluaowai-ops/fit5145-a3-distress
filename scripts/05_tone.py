"""Task 5: annual-report tone scores.

Default: full report text (data/processed/fulltext/) -> data/processed/tone.csv (used by the model).
`--source mdna` scores the MD&A section only -> tone_mdna.csv; `--source mdna_notes` scores
MD&A + financial report (built by 07_mdna_notes.py) -> tone_mdna_notes.csv (robustness scopes).

Dictionary: Yao et al. (2021) Chinese financial sentiment lexicon, annual-report version
(dict/formal_pos.txt, dict/formal_neg.txt; one word per line). No Chinese uncertainty list
is available, so only net tone is scored.

net_tone = (n_pos - n_neg) / (n_pos + n_neg)
n_words counts tokens containing at least one CJK character or letter
(numbers and punctuation are excluded).
"""
import argparse
import re
import time

import jieba
import pandas as pd

from common import DICT_DIR, FULLTEXT_DIR, MDNA_DIR, PROCESSED

SOURCES = {"fulltext": (FULLTEXT_DIR, "tone.csv"), "mdna": (MDNA_DIR, "tone_mdna.csv"),
           "mdna_notes": (PROCESSED / "mdna_notes", "tone_mdna_notes.csv")}
WORDLIKE = re.compile(r"[一-鿿A-Za-z]")


def read_words(path):
    words = (w.strip() for w in path.read_text(encoding="utf-8-sig").splitlines())
    return {w for w in words if w and WORDLIKE.search(w)}


def load_lexicon():
    """Positive / negative word sets; lexicon words are added to jieba so they are not split."""
    pos, neg = read_words(DICT_DIR / "formal_pos.txt"), read_words(DICT_DIR / "formal_neg.txt")
    jieba.setLogLevel(60)
    for w in pos | neg:
        jieba.add_word(w, freq=100000)
    return pos, neg


def score_text(text, pos, neg):
    tokens = [t for t in jieba.lcut(text.replace("\n", "")) if WORDLIKE.search(t)]
    n_pos = sum(t in pos for t in tokens)
    n_neg = sum(t in neg for t in tokens)
    return dict(n_words=len(tokens), n_pos=n_pos, n_neg=n_neg,
                net_tone=(n_pos - n_neg) / (n_pos + n_neg) if n_pos + n_neg else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=SOURCES, default="fulltext")
    text_dir, out_name = SOURCES[ap.parse_args().source]

    pos, neg = load_lexicon()
    print(f"dictionary: {len(pos)} positive, {len(neg)} negative words")

    rows = []
    t0 = time.time()
    for txt in sorted(text_dir.glob("*.txt")):
        code, fy = txt.stem.split("_")
        rows.append(dict(code=code, fiscal_year=int(fy),
                         **score_text(txt.read_text(encoding="utf-8"), pos, neg)))
    print(f"scored {len(rows)} files in {time.time() - t0:.0f}s")
    df = pd.DataFrame(rows)
    df.to_csv(PROCESSED / out_name, index=False, encoding="utf-8-sig")
    print(f"{out_name}: {len(df)} rows (source: {text_dir.name})")
    print(df[["n_words", "n_pos", "n_neg", "net_tone"]].describe().round(4).to_string())


if __name__ == "__main__":
    main()
