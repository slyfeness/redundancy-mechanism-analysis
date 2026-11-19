
"""Reduce only overflowing requests, using the frozen dense encoder's rankings."""

from collections import defaultdict
from functools import cached_property
import json

from prepare_full import read

CONTEXT = 131_072
LIMIT = CONTEXT * 4 // 5


class Budget:
    def __init__(self, model):
        from transformers import AutoTokenizer

        self.tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True, model_max_length=4_000_000)

    def size(self, prompt, payload):
        messages = [{"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        return len(self.tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=True, return_dict=True)["input_ids"])

    def compatible(self, prompt, payload, response_tokens):
        return self.size(prompt, payload) + response_tokens + 512 <= CONTEXT


class Ranking:
    def __init__(self, directory):
        self.directory = directory

    @cached_property
    def blocks(self):
        import numpy as np

        by_doc = defaultdict(list)
        vectors = []
        for rank in range(4):
            rows = read(self.directory / f"blocks-{rank}.json")
            array = np.load(self.directory / f"blocks-{rank}.npy", allow_pickle=False)
            if len(rows) != len(array):
                raise ValueError("block/embedding count mismatch")
            for index, block in enumerate(rows, start=sum(len(a) for a in vectors)):
                by_doc[block["docid"]].append((index, block))
            vectors.append(array)
        return by_doc, np.concatenate(vectors)

    def queries(self, phase, directory=None):
        import numpy as np

        directory = directory or self.directory
        result = {}
        for rank in range(4):
            rows = read(directory / f"{phase}-q-{rank}.json")
            vectors = np.load(directory / f"{phase}-q-{rank}.npy", allow_pickle=False)
            result.update(zip(rows, vectors, strict=True))
        return result

    def rank(self, docids, query_vector):
        by_doc, vectors = self.blocks
        if set(docids) - by_doc.keys():
            raise ValueError("overflowing input is outside the prepared embedding block inventory")
        indexed = [row for docid in docids for row in by_doc[docid]]
        scores = vectors[[index for index, _ in indexed]] @ query_vector
        ranked = sorted(zip((row for _, row in indexed), scores, strict=True),
                        key=lambda pair: (-float(pair[1]), pair[0]["id"]))
        return [block for block, _ in ranked]


def choose(ranked, count_tokens, *, document_ids=(), limit=LIMIT):
    mandatory = {}
    for block in ranked:
        if block["docid"] in document_ids:
            mandatory.setdefault(block["docid"], block["id"])
    if mandatory.keys() != set(document_ids):
        raise ValueError("missing required source document")
    must_keep = set(mandatory.values())
    optional = [b for b in ranked if b["id"] not in must_keep]

    def ordered(n):
        keep = must_keep | {b["id"] for b in optional[:n]}
        return [b for b in ranked if b["id"] in keep]

    def size(n):
        chosen = ordered(n)
        return count_tokens(chosen), chosen

    small_size, small = size(0)
    if small_size > limit:
        raise ValueError("mandatory evidence blocks exceed the reserved input limit")
    low, high, best = 0, len(optional) + 1, (small_size, small)
    while low + 1 < high:
        middle = (low + high) // 2
        tokens, chosen = size(middle)
        if tokens <= limit:
            low, best = middle, (tokens, chosen)
        else:
            high = middle
    return best
