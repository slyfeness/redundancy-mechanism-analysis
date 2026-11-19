"""Sample eligible unknowns and rank local evidence without further Judge calls."""

from collections import Counter
from math import log
import random
import re

SEED = 20261119
WORD = re.compile(r"[^\W_]+")
IGNORE = set("a an and are as at be by for from had has in is it of on or so that the their this to was were with".split())


def terms(text):
    return set(WORD.findall(text.casefold())) - IGNORE


def relevant(passages, target, excerpt):
    docs = [(passage, [(sentence, terms(sentence["text"])) for sentence in passage["sentences"]])
            for passage in passages if passage["sentences"]]
    counts = Counter(term for _, sentences in docs for term in set().union(*(words for _, words in sentences)))
    weights = {word: log((1 + len(docs)) / (1 + counts[word])) + 1 for word in terms(target)}

    def score(words):
        return sum(weights[word] for word in sorted(words & weights.keys()))

    ranked = []
    for order, (passage, sentences) in enumerate(docs):
        best, overlap = max(sentences, key=lambda pair: score(pair[1]))
        aggregate = score(set().union(*(words for _, words in sentences)))
        ranked.append((score(overlap) + 0.25 * aggregate, -order, passage, best))
    return [{**excerpt(passage["text"], sentence), "passage_id": passage["id"],
             "unit_id": passage["unit_id"]} for _, _, passage, sentence in
            sorted(ranked, key=lambda item: item[:2], reverse=True)[:2]]


def sample_unknown(verdicts, track_question, records, visible, excerpt, *, count=20):
    eligible = sorted((row for row in verdicts if row["status"] == "unknown"
                       and row["assertion_id"] is not None
                       and not re.search(r"\bdifferent\s+entity\b", row["reason"], flags=re.I)
                       and sum(bool(p["sentences"]) for p in visible[row["trajectory_id"]]) >= 2),
                      key=lambda row: (row["trajectory_id"], row["assertion_id"]))
    picks = random.Random(SEED).sample(eligible, min(count, len(eligible)))
    selected = []
    for row in picks:
        tid, cid = row["trajectory_id"], row["assertion_id"]
        record = records[track_question[tid]]
        claim = next(c for c in record["conditions"] if c["id"] == cid)
        subject = next((e["name"] for e in record["entities"] if e["var"] == claim["subject"]), "")
        hits = relevant(visible[tid], f'{subject} {claim["claim"]}', excerpt)
        selected.append({"trajectory_id": tid, "query_id": track_question[tid], "assertion_id": cid,
                         "claim": claim["claim"], "reason": row["reason"], "passages": hits})
    return selected, len(eligible)
