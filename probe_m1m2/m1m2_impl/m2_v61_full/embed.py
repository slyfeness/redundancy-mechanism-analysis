
"""Embed immutable training evidence blocks and the specified retrieval queries."""

from argparse import ArgumentParser
import json
import os
from pathlib import Path

from prepare_full import digest, read

MODEL_SHA = "dcccf7c7890c8debc4af8dace8d6acd8dd50bd56d50d4d8b60529381ba3de3d7"
CHUNK_TOKENIZER_SHA = "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4"
QUERY_PREFIX = "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:"
CANDIDATE_MIN = 90_000


def dump(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def split_document(docid, text, tokenizer):
    offsets = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True,
                        verbose=False)["offset_mapping"]
    start = 0
    result = []
    for block, offset in enumerate(range(512, len(offsets), 512)):
        end = max(start, offsets[offset][0])
        if end > start:
            result.append({"id": f"{docid}:{block}", "docid": docid, "text": text[start:end]})
        start = end
    result.append({"id": f"{docid}:{(len(offsets) - 1) // 512 if offsets else 0}",
                   "docid": docid, "text": text[start:]})
    if "".join(row["text"] for row in result) != text:
        raise ValueError("evidence block offsets did not preserve source text")
    return result


def candidates(prep):
    return {qid for qid, e in read(prep / "estimates.json").items()
            if max(e.values()) >= CANDIDATE_MIN}


def encode(rows, *, model, tokenizer, device, query):
    import torch
    import numpy as np

    result = []
    for start in range(0, len(rows), 24):
        texts = [r[1] for r in rows[start:start + 24]]
        if query:
            features = tokenizer([QUERY_PREFIX + s for s in texts], padding=True, truncation=True,
                                 max_length=8192, return_tensors="pt")
        else:
            ids = tokenizer(texts, padding=False, add_special_tokens=True)["input_ids"]
            features = tokenizer.pad({"input_ids": [x + [tokenizer.eos_token_id] for x in ids]},
                                     padding=True, return_attention_mask=True, return_tensors="pt")
        features = {key: value.to(device) for key, value in features.items()}
        with torch.inference_mode(), torch.amp.autocast("cuda"):
            encoded = model.encode_query(features) if query else model.encode_passage(features)
        result.append(encoded.float().cpu().numpy())
        if not query and (start // 24) % 20 == 0:
            print(json.dumps({"rank": device, "embedded": min(start + 24, len(rows)), "blocks": len(rows)}),
                  flush=True)
    return np.concatenate(result) if result else np.empty((0, model.encoder.config.hidden_size), dtype=np.float32)


def main():
    parser = ArgumentParser()
    parser.add_argument("phase", choices=("first", "gold"))
    parser.add_argument("--prep", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--queries", type=Path)
    args = parser.parse_args()

    import numpy as np
    import torch
    from tevatron.retriever.driver.encode import DenseModel
    from transformers import AutoTokenizer

    rank, count = int(os.environ["LOCAL_RANK"]), int(os.environ["LOCAL_WORLD_SIZE"])
    if count != 4 or torch.cuda.device_count() != count:
        raise ValueError("expected four assigned, visible GPUs")
    device = f"cuda:{rank}"
    torch.cuda.set_device(rank)
    model_dir = args.base / "models/Qwen3-Embedding-8B"
    chunk_dir = args.base / "tokenizers/Qwen3-0.6B"
    if (digest(model_dir / "config.json"), digest(chunk_dir / "tokenizer.json")) != (MODEL_SHA, CHUNK_TOKENIZER_SHA):
        raise ValueError("frozen embedding assets changed")
    model = DenseModel.load(str(model_dir), pooling="eos", normalize=True, lora_name_or_path=None,
                            torch_dtype=torch.float16, attn_implementation="sdpa").to(device).eval()
    tokenizer = AutoTokenizer.from_pretrained(model_dir, padding_side="left", local_files_only=True)
    questions = read(args.prep / "questions.json")
    if args.phase == "first":
        selected = candidates(args.prep)
        docs = sorted({docid for qid in selected
                       for key in ("gold_docs", "evidence_docs") for docid in questions[qid][key]})
        source = read(args.prep / "documents.json")
        chunk_tokenizer = AutoTokenizer.from_pretrained(chunk_dir, local_files_only=True)
        blocks = [block for docid in docs[rank::count] for block in split_document(docid, source[docid], chunk_tokenizer)]
        arr = encode([(b["id"], b["text"]) for b in blocks], model=model, tokenizer=tokenizer,
                     device=device, query=False)
        np.save(args.out / f"blocks-{rank}.npy", arr, allow_pickle=False)
        dump(args.out / f"blocks-{rank}.json", blocks)
        query_rows = [(qid, questions[qid]["question"]) for qid in sorted(selected)]
    else:
        query_rows = [(r["id"], r["text"]) for r in read(args.queries)]
    work = query_rows[rank::count]
    arr = encode(work, model=model, tokenizer=tokenizer, device=device, query=True)
    np.save(args.out / f"{args.phase}-q-{rank}.npy", arr, allow_pickle=False)
    dump(args.out / f"{args.phase}-q-{rank}.json", [key for key, _ in work])
    print(json.dumps({"phase": args.phase, "rank": rank, "queries": len(work), "complete": 1}), flush=True)


if __name__ == "__main__":
    main()
