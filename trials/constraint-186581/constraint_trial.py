"""Constraint-extraction trial: 10 questions, fixed JSON format, loose checks, human review sheet.

Calls only a loopback OpenAI-compatible server (local gpt-oss-120b). Nothing is rejected:
every check only adds a flag, so the reviewer sees the raw model output.

Outputs (all contain question text, keep them private):
  results.jsonl   one row per question: sentences, model output, flags, raw receipt
  review.md       sheet for manual review (missing / invented / granularity)
  summary.json    counts only, no question text
"""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

SCHEMA = {
    "type": "object",
    "properties": {
        "answer_type": {"type": "string"},
        "constraints": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "sentence": {"type": "integer"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "certain": {"type": "boolean"},
                },
                "required": ["id", "text", "sentence", "keywords", "certain"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answer_type", "constraints"],
    "additionalProperties": False,
}


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def norm(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def split_sentences(question):
    parts = re.split(r"(?<=[.!?;。！？；])\s+", question.strip())
    return [p for p in (s.strip() for s in parts) if p]


def check(output, sentences, question):
    """Loose checks. Returns a list of flags per constraint plus question-level flags."""
    flags = []
    rows = output.get("constraints") or []
    if not rows:
        flags.append("no_constraints")
    if not str(output.get("answer_type", "")).strip():
        flags.append("no_answer_type")
    seen_text = set()
    per_row = []
    for i, row in enumerate(rows, 1):
        f = []
        if row.get("id") != f"C{i}":
            f.append("id_out_of_order")
        text = norm(row.get("text", ""))
        if not text:
            f.append("empty_text")
        if text in seen_text:
            f.append("duplicate_text")
        seen_text.add(text)
        s = row.get("sentence")
        valid_s = isinstance(s, int) and 1 <= s <= len(sentences)
        if not valid_s:
            f.append("bad_sentence_number")
        kws = [k for k in row.get("keywords", []) if isinstance(k, str) and k.strip()]
        if not kws:
            f.append("no_keywords")
        for k in kws:
            if valid_s and norm(k) in norm(sentences[s - 1]):
                continue
            f.append("keyword_in_other_sentence" if norm(k) in norm(question) else "keyword_not_in_question")
        if not row.get("certain", True):
            f.append("model_uncertain")
        per_row.append(sorted(set(f)))
    return flags, per_row


class LocalModel:
    def __init__(self, url, model, prompt, timeout, max_tokens):
        parsed = urlsplit(url)
        if parsed.scheme != "http" or not ipaddress.ip_address(parsed.hostname).is_loopback:
            raise SystemExit("model URL must be http on a numeric loopback address")
        self.endpoint = url.rstrip("/") + "/chat/completions"
        self.model, self.prompt, self.timeout, self.max_tokens = model, prompt, timeout, max_tokens
        self.opener = build_opener(ProxyHandler({}))

    def ask(self, sentences):
        body = {
            "model": self.model, "temperature": 0, "max_tokens": self.max_tokens,
            "reasoning_effort": "low",
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "constraints", "strict": True, "schema": SCHEMA}},
            "messages": [{"role": "system", "content": self.prompt},
                         {"role": "user", "content": json.dumps(
                             {"sentences": [{"n": i, "text": s} for i, s in enumerate(sentences, 1)]},
                             ensure_ascii=False)}],
        }
        req = Request(self.endpoint, json.dumps(body, ensure_ascii=False).encode("utf-8"),
                      {"Content-Type": "application/json"})
        t0 = time.time()
        with self.opener.open(req, timeout=self.timeout) as stream:
            env = json.loads(stream.read())
        choice = env["choices"][0]
        receipt = {"seconds": round(time.time() - t0, 2), "finish_reason": choice.get("finish_reason"),
                   "served_model": env.get("model"), "usage": env.get("usage")}
        if env.get("model") != self.model:
            raise ValueError(f"served model mismatch: {env.get('model')}")
        if choice.get("finish_reason") != "stop":
            raise ValueError(f"generation did not finish: {choice.get('finish_reason')}")
        content = choice["message"]["content"]
        receipt["raw_content"] = content
        return json.loads(content), receipt


def pick_questions(index_rows, ids_file, n, split):
    questions = {}
    for row in index_rows:
        questions.setdefault(str(row["question_id"]), {"question": row["question"], "split": row.get("split")})
    if ids_file:
        wanted = [line.strip() for line in Path(ids_file).read_text(encoding="utf-8").splitlines() if line.strip()]
        missing = [q for q in wanted if q not in questions]
        if missing:
            raise SystemExit(f"question ids not in index: {missing}")
        return [(q, questions[q]["question"]) for q in wanted]
    pool = sorted((q for q, v in questions.items() if split in (None, v["split"])), key=lambda q: sha("20261114|" + q))
    return [(q, questions[q]["question"]) for q in pool[:n]]


def write_review(path, results):
    lines = ["# 约束提取试跑：人工检查表", "",
             "每题看三件事：**漏**（题目里的条件没拆出来）、**编**（这一条在注明的句子里找不到依据）、"
             "**粒度**（两件事塞进一条，或一件事拆太碎）。在最后三列填 ✓ 或写问题。", ""]
    for r in results:
        lines += [f"## 题目 {r['question_id']}", ""]
        for i, s in enumerate(r["sentences"], 1):
            lines.append(f"{i}. {s}")
        lines.append("")
        if r.get("error"):
            lines += [f"**调用失败**：{r['error']}", ""]
            continue
        out = r["output"]
        lines += [f"答案类型：{out.get('answer_type', '')}", "",
                  "| 编号 | 条件 | 句 | 关键词 | 确定 | 程序标记 | 编? | 粒度? | 备注 |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for row, flags in zip(out.get("constraints", []), r["row_flags"]):
            kws = " / ".join(row.get("keywords", []))
            lines.append(f"| {row.get('id')} | {row.get('text')} | {row.get('sentence')} | {kws} | "
                         f"{'是' if row.get('certain') else '否'} | {', '.join(flags) or '—'} |  |  |  |")
        qf = ", ".join(r["question_flags"]) or "—"
        lines += ["", f"题目级标记：{qf}　　**漏了什么**：", ""]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-index", required=True, help="private input_index.jsonl")
    ap.add_argument("--question-ids", help="optional file, one question_id per line")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--split", default="dev")
    ap.add_argument("--prompt", default=str(Path(__file__).with_name("constraint_prompt.md")))
    ap.add_argument("--url", required=True)
    ap.add_argument("--model", default="gpt-oss-120b")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--output-dir", required=True)
    args = ap.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=False)
    prompt = Path(args.prompt).read_text(encoding="utf-8")
    rows = [json.loads(l) for l in Path(args.input_index).read_text(encoding="utf-8-sig").splitlines() if l.strip()]
    chosen = pick_questions(rows, args.question_ids, args.n, args.split)
    model = LocalModel(args.url, args.model, prompt, args.timeout, args.max_tokens)

    results = []
    for qid, question in chosen:
        sentences = split_sentences(question)
        r = {"question_id": qid, "question_sha256": sha(question), "sentences": sentences}
        try:
            output, receipt = model.ask(sentences)
            r["output"], r["receipt"] = output, receipt
            r["question_flags"], r["row_flags"] = check(output, sentences, question)
        except Exception as exc:  # record every failure; no retry, we want to see raw behaviour
            r["error"] = f"{type(exc).__name__}: {exc}"
        results.append(r)
        print(qid, "error" if "error" in r else f"{len(r['output'].get('constraints', []))} constraints", flush=True)

    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    write_review(out_dir / "review.md", results)

    flag_counts = {}
    for r in results:
        for fl in r.get("question_flags", []) + [x for fs in r.get("row_flags", []) for x in fs]:
            flag_counts[fl] = flag_counts.get(fl, 0) + 1
    ok = [r for r in results if "error" not in r]
    summary = {
        "questions": len(results), "call_failures": len(results) - len(ok),
        "constraints_total": sum(len(r["output"].get("constraints", [])) for r in ok),
        "constraints_with_any_flag": sum(1 for r in ok for fs in r["row_flags"] if fs),
        "flag_counts": flag_counts,
        "prompt_sha256": sha(prompt), "model": args.model,
        "question_sha256": [r["question_sha256"] for r in results],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
