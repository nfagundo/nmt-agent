import re, unicodedata, gzip
from pathlib import Path

URLISH = re.compile(r"(https?://|www\.)", re.IGNORECASE)
HTMLISH = re.compile(r"(<[^>]+>|&nbsp;|&#\d+;)")
CTRL = re.compile(r"[\u0000-\u001f]")

LEADING_ANNOT = re.compile(r"^\s*[\[\(\{]?\d+(?:\.\d+)?[\]\)\}]?\s*")

BRACKET_CHARS = re.compile(r"[\[\]\(\)\{\}]")

# Zero-width / BOM characters that often appear as "﻿﻿﻿"
ZERO_WIDTH = re.compile(r"[\uFEFF\u200B\u200C\u200D\u2060]")

LEADING_COLON_NUM = re.compile(r"^\s*:\d+(?:\.\d+)?\s*")

# Monolingual spam patterns
LEADING_PUNCT_SPAM = re.compile(r"^\s*[!?.;,:'\"*_~\-]{2,}")
TEMPLATE_ARTIFACTS = re.compile(r"(\$\d+|{{|}}|\[\[|\]\])")
REPEATED_PUNCT = re.compile(r"([!?.])\1{3,}")  # e.g., !!!! or ????


def normalize(s: str, lowercase=True) -> str:
    s = s.strip()

    s = ZERO_WIDTH.sub("", s)

    s = unicodedata.normalize("NFKC", s)

    s = LEADING_COLON_NUM.sub("", s)

    s = LEADING_ANNOT.sub("", s)
    s = BRACKET_CHARS.sub(" ", s)

    s = CTRL.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if lowercase:
        s = s.lower()
    return s

def bad_line(s: str) -> bool:
    if not s:
        return True
    if "�" in s:
        return True
    if URLISH.search(s) or HTMLISH.search(s):
        return True
    if not any(ch.isalpha() for ch in s):
        return True
    return False

def noisy_mono_line(s: str) -> bool:
    """Strict filtering for monolingual spam/artifacts."""
    # obvious spam formatting
    if LEADING_PUNCT_SPAM.search(s):
        return True
    if TEMPLATE_ARTIFACTS.search(s):
        return True
    if REPEATED_PUNCT.search(s):
        return True

    # letter density: drop lines that are mostly symbols/numbers
    letters = sum(ch.isalpha() for ch in s)
    total = len(s)
    if total > 0 and letters / total < 0.6:
        return True

    # weird character density (non-alnum, non-space, not standard punctuation)
    weird = sum(
        not (ch.isalnum() or ch.isspace() or ch in ".,?!:;'\"()-")
        for ch in s
    )
    if total > 0 and weird / total > 0.2:
        return True

    return False

def clean_parallel(en_path, sw_path, score_path, out_en, out_sw, min_score = 1.1, max_words=80, max_ratio=3.0, dedup=False):
    Path(out_en).parent.mkdir(parents=True, exist_ok=True)

    kept = dropped = 0
    seen = set() if dedup else None  # optional dedup
    def helper_no_score(en_path, sw_path, out_en, out_sw, max_words, max_ratio):
        nonlocal kept, dropped, seen
        pairs = 0
        with open(en_path, "r", encoding="utf-8", errors="replace") as fe, \
             open(sw_path, "r", encoding="utf-8", errors="replace") as fs, \
             open(out_en, "w", encoding="utf-8") as oe, \
             open(out_sw, "w", encoding="utf-8") as os:

            for en_raw, sw_raw in zip(fe, fs):
                pairs += 1
                en = normalize(en_raw)
                sw = normalize(sw_raw)

                if bad_line(en) or bad_line(sw):
                    dropped += 1
                    continue

                en_w = en.split()
                sw_w = sw.split()

                if len(en_w) > max_words or len(sw_w) > max_words:
                    dropped += 1
                    continue

                ratio = max(len(en_w), len(sw_w)) / max(1, min(len(en_w), len(sw_w)))
                if ratio > max_ratio:
                    dropped += 1
                    continue
                if seen is not None:
                    key = (en, sw)
                    if key in seen:
                        dropped += 1
                        continue
                    seen.add(key)

                oe.write(en + "\n")
                os.write(sw + "\n")
                kept += 1

                # Progress update every 1M pairs
                if pairs % 1_000_000 == 0:
                    print(f"[parallel] processed={pairs:,} kept={kept:,} dropped={dropped:,}")

        print(f"[parallel] kept={kept:,} dropped={dropped:,}")
    def helper_with_score(en_path, sw_path, score_path, out_en, out_sw, min_score, max_words, max_ratio):
        nonlocal kept, dropped, seen
        pairs = 0
        with open(en_path, encoding="utf-8", errors="replace") as fe, \
             open(sw_path, encoding="utf-8", errors="replace") as fs, \
             open(score_path, encoding="utf-8") as fscore, \
             open(out_en, "w", encoding="utf-8") as oe, \
             open(out_sw, "w", encoding="utf-8") as os:

            for en_raw, sw_raw, score_raw in zip(fe, fs, fscore):
                pairs += 1

                try:
                    score = float(score_raw.strip())
                except ValueError:
                    dropped += 1
                    continue

                if score < min_score:
                    dropped += 1
                    continue

                en = normalize(en_raw)
                sw = normalize(sw_raw)

                if bad_line(en) or bad_line(sw):
                    dropped += 1
                    continue

                en_w = en.split()
                sw_w = sw.split()

                if len(en_w) > max_words or len(sw_w) > max_words:
                    dropped += 1
                    continue

                ratio = max(len(en_w), len(sw_w)) / max(1, min(len(en_w), len(sw_w)))
                if ratio > max_ratio:
                    dropped += 1
                    continue

                oe.write(en + "\n")
                os.write(sw + "\n")
                kept += 1

                # Progress update every 1M pairs
                if pairs % 1_000_000 == 0:
                    print(f"[parallel] processed={pairs:,} kept={kept:,} dropped={dropped:,}")

        print(f"[parallel] kept={kept:,} dropped={dropped:,}")
    if score_path is None:
        helper_no_score(en_path, sw_path, out_en, out_sw, max_words, max_ratio)
        return
    else:
        helper_with_score(en_path, sw_path, score_path, out_en, out_sw, min_score, max_words, max_ratio)
        return

def clean_mono_gz(gz_path, out_path, max_words=80, dedup=False):
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    kept = dropped = 0
    seen = set() if dedup else None  # optional dedup
    processed = 0

    with gzip.open(gz_path, "rt", encoding="utf-8", errors="replace") as fin, \
         open(out_path, "w", encoding="utf-8") as fout:

        for line in fin:
            processed += 1
            s = normalize(line)
            if bad_line(s):
                dropped += 1
                continue

            # Apply strict monolingual filtering
            if noisy_mono_line(s):
                dropped += 1
                continue

            if len(s.split()) > max_words:
                dropped += 1
                continue
            if seen is not None:
                if s in seen:
                    dropped += 1
                    continue
                seen.add(s)

            fout.write(s + "\n")
            kept += 1

            # Progress update every 1M lines
            if processed % 1_000_000 == 0:
                print(f"[mono] processed={processed:,} kept={kept:,} dropped={dropped:,}")

    print(f"[mono] {gz_path} -> kept={kept:,} dropped={dropped:,}")

if __name__ == "__main__":
    clean_parallel(
        "data/raw/nllb-en-sw.txt/NLLB.en-sw.en",
        "data/raw/nllb-en-sw.txt/NLLB.en-sw.sw",
        "data/raw/nllb-en-sw.txt/NLLB.en-sw.scores",
        "data/processed/nllb/train.clean.en",
        "data/processed/nllb/train.clean.sw"
    )
    clean_mono_gz("data/raw/nllb-en.txt.gz", "data/processed/nllb/mono_clean.en")
    clean_mono_gz("data/raw/nllb-sw.txt.gz", "data/processed/nllb/mono_clean.sw")
    clean_parallel(
        "data/raw/ccmatrix-en-sw.txt/ccmatrix.en-sw.en",
        "data/raw/ccmatrix-en-sw.txt/ccmatrix.en-sw.sw",
        "data/raw/ccmatrix-en-sw.txt/ccmatrix.en-sw.scores",
        "data/processed/ccmatrix/train.clean.en",
        "data/processed/ccmatrix/train.clean.sw")
    clean_mono_gz("data/raw/ccmatrix-en.txt.gz", "data/processed/ccmatrix/mono_clean.en")
    clean_mono_gz("data/raw/ccmatrix-sw.txt.gz", "data/processed/ccmatrix/mono_clean.sw")
    clean_parallel(
        "data/raw/ccaligned-en-sw.txt/ccaligned.en-sw.en",
        "data/raw/ccaligned-en-sw.txt/ccaligned.en-sw.sw",
        None,
        "data/processed/ccaligned/train.clean.en",
        "data/processed/ccaligned/train.clean.sw"
    )
    clean_mono_gz("data/raw/ccaligned-en.txt.gz", "data/processed/ccaligned/mono_clean.en")
    clean_mono_gz("data/raw/ccaligned-sw.txt.gz", "data/processed/ccaligned/mono_clean.sw")
