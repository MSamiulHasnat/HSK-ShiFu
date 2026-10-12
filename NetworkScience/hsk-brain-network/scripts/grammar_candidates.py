#!/usr/bin/env python3
"""Candidate grammar-rule -> sentence links, for agents to verify.

For every grammar node that has fewer than MIN_LINKS sentence links in network.json, take its key
characters (the Hanzi in its label), find sentence nodes whose own Chinese text contains them, rank the
hits (same chapter first, then same HSK level, then shorter sentence) and keep the best PER_RULE.
Writes grammar_cand_NN.json (BATCH rules each) into the given folder.  Usage:
    grammar_candidates.py <data folder containing network.json> <out folder>
"""
import collections
import json
import re
import sys
from pathlib import Path

DATA = Path(sys.argv[1])
OUT = Path(sys.argv[2])
MIN_LINKS, PER_RULE, BATCH = 1, 8, 28
HZ = re.compile(r"[一-鿿]+")
NOISE = ("Review", "Lesson", "Notes", "Learned So Far")

net = json.loads((DATA / "network.json").read_text(encoding="utf-8"))
nodes = {n["id"]: n for n in net["nodes"]}
sent_links = collections.Counter()
chapter_of = collections.defaultdict(set)
for e in net["edges"]:
    a, b = nodes[e["s"]], nodes[e["t"]]
    for g, s in ((a, b), (b, a)):
        if g["type"] == "grammar" and s["type"] == "sentence":
            sent_links[g["id"]] += 1
        if g["type"] in ("grammar", "sentence") and s["type"] == "chapter":
            chapter_of[g["id"]].add(s["id"])


def sentence_text(label):
    """The sentence itself: drop the 'Example:' prefix and the '(illustrating ...)' gloss."""
    t = re.sub(r"^\s*(Example|Examples|Example Sentence)s?\s*[:：]\s*", "", label)
    return re.sub(r"\s*[(（].*$", "", t)


def keys(label):
    """Key Hanzi chunks of a grammar label, longest first; alternatives like 都/还/也 are split."""
    core = re.sub(r"\(.*?\)|（.*?）", "", label)
    parts = []
    for chunk in re.split(r"[…⋯.+＋/、，,\s]+|[A-Za-z]+", core):
        parts += HZ.findall(chunk)
    return [p for p in dict.fromkeys(parts) if p]


sentences = [(n, sentence_text(n["label"])) for n in nodes.values() if n["type"] == "sentence"]
sentences = [(n, t) for n, t in sentences if HZ.search(t)]

todo = [n for n in nodes.values() if n["type"] == "grammar" and sent_links[n["id"]] < MIN_LINKS]
cands, no_key = [], 0
for g in sorted(todo, key=lambda n: (n["lvs"], n["pages"][:1], n["label"])):
    ks = keys(g["label"])
    if not ks or any(w in g["label"] for w in NOISE) and len(ks) < 1:
        no_key += 1
        continue
    # a sentence must contain the first key (the head word); further keys only improve the rank
    hits = []
    for s, t in sentences:
        if ks[0] not in t:
            continue
        lv_ok = min(s["lvs"] or [9]) <= max(g["lvs"] or [3])
        if not lv_ok:
            continue
        same_ch = bool(chapter_of[g["id"]] & chapter_of[s["id"]])
        more = sum(k in t for k in ks[1:])
        same_lv = bool(set(s["lvs"]) & set(g["lvs"]))
        hits.append((-int(same_ch), -more, -int(same_lv), len(t), s["id"], t))
    hits.sort()
    cands.append({
        "grammar": g["id"], "label": g["label"], "levels": g["lvs"], "keys": ks, "n_hits": len(hits),
        "candidates": [{"sentence": h[4], "text": h[5], "same_chapter": h[0] == -1} for h in hits[:PER_RULE]],
    })

OUT.mkdir(parents=True, exist_ok=True)
for i in range(0, len(cands), BATCH):
    p = OUT / f"grammar_cand_{i // BATCH + 1:02d}.json"
    p.write_text(json.dumps(cands[i:i + BATCH], ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{len(todo)} grammar rules below {MIN_LINKS} links; {len(cands)} have key characters ({no_key} do not);"
      f" {sum(1 for c in cands if c['candidates'])} have candidates; wrote {(len(cands) + BATCH - 1) // BATCH} batches")
