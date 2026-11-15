"""Two-pass question constraint trial. All model requests stay on loopback."""

import argparse
from collections import Counter
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


def object_schema(**fields):
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def array_schema(items):
    return {"type": "array", "items": items}


STRING = {"type": "string"}
FACT = {"text": STRING, "keywords": array_schema(STRING), "certain": {"type": "boolean"}}
EXTRACT_SCHEMA = object_schema(
    answer_type=STRING, answer_format=STRING, global_notes=array_schema(STRING),
    constraints=array_schema(object_schema(id=STRING, **FACT)),
)
AUDIT_SCHEMA = object_schema(
    missing=array_schema(object_schema(**FACT)),
    not_constraints=array_schema(object_schema(id=STRING, reason=STRING)),
)
ADVISORY_FLAGS = {"keyword_repeats", "model_uncertain"}


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def norm(text):
    return " ".join(unicodedata.normalize("NFKC", text).lower().split())


def keyword_matches(question, keyword):
    if not keyword:
        return []
    return [
        match.span()
        for match in re.finditer(re.escape(keyword), question)
        if (not keyword[0].isalnum() or match.start() == 0 or not question[match.start() - 1].isalnum())
        and (not keyword[-1].isalnum() or match.end() == len(question) or not question[match.end()].isalnum())
    ]


def question_offsets(question):
    """Map normalized characters back to source spans for highlighting."""
    spans = []
    previous = ""
    for end in range(1, len(question) + 1):
        current = norm(question[:end])
        common = 0
        while common < min(len(current), len(previous)) and current[common] == previous[common]:
            common += 1
        start = spans[common][0] if common < len(spans) else end - 1
        if common < len(current) and current[common] == " ":
            space_start = spans[common - 1][1] if common else 0
            spans[common:] = [(space_start, start)] + [(start, end)] * (len(current) - common - 1)
        else:
            spans[common:] = [(start, end)] * (len(current) - common)
        previous = current
    return previous, spans


def highlight(question, keywords):
    if not keywords:
        return question
    normalized, source_spans = question_offsets(question)
    matches = sorted((source_spans[start][0], source_spans[end - 1][1])
                     for keyword in keywords for start, end in keyword_matches(normalized, keyword))
    merged = []
    for start, end in matches:
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    parts, last = [], 0
    for start, end in merged:
        parts.extend((question[last:start], "**", question[start:end], "**"))
        last = end
    return "".join(parts) + question[last:]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class CallFailure(Exception):
    pass


def check_shape(value, schema):
    """Check the transport shape while leaving semantic checks to flags."""
    kind = schema["type"]
    if kind == "object":
        return (isinstance(value, dict) and value.keys() == schema["properties"].keys()
                and all(check_shape(value[key], spec) for key, spec in schema["properties"].items()))
    if kind == "array":
        return isinstance(value, list) and all(check_shape(item, schema["items"]) for item in value)
    return isinstance(value, str) if kind == "string" else type(value) is bool


class LocalModel:
    def __init__(self, url, model, timeout, max_tokens, reasoning_effort):
        parsed = urlsplit(url)
        try:
            loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = False
        if parsed.scheme != "http" or not loopback or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("model URL must be HTTP on a numeric loopback address")
        self.endpoint = url.rstrip("/") + "/chat/completions"
        self.model, self.timeout, self.max_tokens = model, timeout, max_tokens
        self.reasoning_effort = reasoning_effort
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def ask(self, name, schema, prompt, payload, receipt):
        body = {"model": self.model, "temperature": 0, "reasoning_effort": self.reasoning_effort,
                "max_tokens": self.max_tokens,
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": name, "strict": True, "schema": schema}},
                "messages": [{"role": "system", "content": prompt},
                             {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]}
        request = Request(self.endpoint, json.dumps(body, ensure_ascii=False).encode("utf-8"),
                          {"Content-Type": "application/json"})
        start = time.monotonic()
        receipt.update(seconds=None, usage=None, completion_tokens=None, raw_content=None,
                       finish_reason=None, served_model=None)
        try:
            with self.opener.open(request, timeout=self.timeout) as stream:
                envelope = json.load(stream)
            choice = envelope["choices"][0]
            content = choice["message"]["content"]
            usage = envelope.get("usage")
            receipt.update(usage=usage, completion_tokens=usage.get("completion_tokens") if isinstance(usage, dict) else None,
                           raw_content=content,
                           finish_reason=choice.get("finish_reason"), served_model=envelope.get("model"))
            if receipt["served_model"] != self.model:
                raise CallFailure("served_model_mismatch")
            if receipt["finish_reason"] != "stop":
                raise CallFailure("generation_not_finished")
            result = json.loads(content)
            if not check_shape(result, schema):
                raise CallFailure("invalid_response_shape")
            return result
        except HTTPError as exc:
            raise CallFailure(f"http_{exc.code}") from exc
        except (URLError, OSError):
            raise CallFailure("loopback_transport_error") from None
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            raise CallFailure("invalid_response_json_or_envelope") from None
        finally:
            receipt["seconds"] = round(time.monotonic() - start, 2)


def annotate(row):
    extracted = row["extraction"]
    audit = row["audit"] or {"missing": [], "not_constraints": []}
    constraints = [{**item, "source": "extract"} for item in extracted["constraints"]]
    constraints.extend({**item, "id": f"A{i}", "source": "audit"} for i, item in enumerate(audit["missing"], 1))
    objections = audit["not_constraints"]
    flagged_ids = {item["id"] for item in objections}
    question_flags = []
    if not constraints:
        question_flags.append("no_constraints")
    if not extracted["answer_type"].strip():
        question_flags.append("no_answer_type")
    if row["audit_error"]:
        question_flags.append("audit_failed")

    seen = set()
    normalized_question = norm(row["question"])
    row_flags = []
    for i, item in enumerate(constraints, 1):
        flags = set()
        if item["source"] == "extract" and item["id"] != f"C{i}":
            flags.add("id_out_of_order")
        text = norm(item["text"])
        if not text:
            flags.add("empty_text")
        if text in seen:
            flags.add("duplicate_text")
        seen.add(text)
        keywords = {norm(keyword) for keyword in item["keywords"] if norm(keyword)}
        if not keywords:
            flags.add("no_keywords")
        for keyword in keywords:
            count = len(keyword_matches(normalized_question, keyword))
            if count == 0:
                flags.add("keyword_not_in_question")
            elif count > 1:
                flags.add("keyword_repeats")
        if not item["certain"]:
            flags.add("model_uncertain")
        if item["source"] == "extract" and item["id"] in flagged_ids:
            flags.add("audit_says_not_constraint")
        row_flags.append(sorted(flags))
    row.update(constraints=constraints, not_constraints=objections,
               question_flags=question_flags, row_flags=row_flags)


def run_question(qid, question, model, extract_prompt, audit_prompt):
    row = {"question_id": qid, "question_sha256": sha(question), "question": question,
           "extraction": None, "extract_receipt": {}, "audit": None, "audit_receipt": None,
           "error": None, "audit_error": None, "constraints": [], "not_constraints": [],
           "question_flags": [], "row_flags": []}
    try:
        row["extraction"] = model.ask("extract", EXTRACT_SCHEMA, extract_prompt, {"question": question},
                                      row["extract_receipt"])
    except CallFailure as exc:
        row["error"] = str(exc)
        return row

    row["audit_receipt"] = {}
    try:
        row["audit"] = model.ask("audit", AUDIT_SCHEMA, audit_prompt,
                                 {"question": question, "extraction": row["extraction"]}, row["audit_receipt"])
    except CallFailure as exc:
        row["audit_error"] = str(exc)
    annotate(row)
    return row


def table_line(*cells):
    safe = [str(value).replace("|", r"\|").replace("\r", "").replace("\n", "<br>") for value in cells]
    return "| " + " | ".join(safe) + " |"


def write_review(path, rows):
    labels = {"extract": "抽取", "audit": "补漏"}
    lines = ["# 约束提取 v4 人工检查表", ""]
    for row in rows:
        keywords = {norm(keyword) for item in row["constraints"] for keyword in item["keywords"]}
        lines.extend((f"## 题目 {row['question_id']}", "", highlight(row["question"], keywords), ""))
        extraction = row["extraction"]
        if row["error"]:
            lines.extend((f"**抽取失败**：{row['error']}", ""))
        else:
            notes = " / ".join(extraction["global_notes"]) or "—"
            lines.extend((f"答案类型：{extraction['answer_type'] or '—'} / "
                          f"回答格式：{extraction['answer_format'] or '—'} / 全局说明：{notes}", "",
                          table_line("编号", "条件", "关键词", "确定", "来源", "程序标记（附查漏意见）",
                                     "漏?", "编?", "粒度?", "备注"), table_line(*["---"] * 10)))
            opinions = {}
            for item in row["not_constraints"]:
                opinions.setdefault(item["id"], []).append(item["reason"])
            used_ids = set()
            for item, flags in zip(row["constraints"], row["row_flags"]):
                notes = list(flags)
                if item["source"] == "extract":
                    notes.extend(opinions.get(item["id"], ()))
                    used_ids.add(item["id"])
                lines.append(table_line(item["id"], item["text"], " / ".join(item["keywords"]),
                                        "是" if item["certain"] else "否", labels[item["source"]],
                                        " / ".join(notes) or "—", "", "", "", ""))
            if row["audit_error"]:
                lines.extend(("", f"**查漏失败**：{row['audit_error']}"))
            for cid in sorted(opinions.keys() - used_ids):
                lines.extend(("", f"**查漏意见（未知编号 {cid}）**：" + " / ".join(opinions[cid])))
        lines.extend(("", "题目级标记：" + (", ".join(row["question_flags"]) or "—") + " / **漏了什么**：", ""))
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def summarize(rows, extract_prompt, audit_prompt, model, reasoning_effort):
    per_question = {}
    flags = Counter()
    warnings = 0
    for row in rows:
        counts = Counter(item["source"] for item in row["constraints"])
        per_question[row["question_id"]] = {
            "extracted": counts["extract"], "added_by_audit": counts["audit"],
            "objections": len(row["not_constraints"]), "error": row["error"] or row["audit_error"],
        }
        flags.update(row["question_flags"])
        for item_flags in row["row_flags"]:
            flags.update(item_flags)
            warnings += bool(set(item_flags) - ADVISORY_FLAGS)
    receipts = [row[key] for row in rows for key in ("extract_receipt", "audit_receipt") if row[key] is not None]
    return {"questions": len(rows), "extract_failures": sum(bool(row["error"]) for row in rows),
            "audit_failures": sum(bool(row["audit_error"]) for row in rows),
            "constraints_extracted": sum(item["extracted"] for item in per_question.values()),
            "constraints_added_by_audit": sum(item["added_by_audit"] for item in per_question.values()),
            "audit_not_constraint_objections": sum(item["objections"] for item in per_question.values()),
            "constraints_with_warning": warnings, "flag_counts": dict(sorted(flags.items())),
            "per_question": per_question, "extract_prompt_sha256": sha(extract_prompt),
            "audit_prompt_sha256": sha(audit_prompt), "model": model, "reasoning_effort": reasoning_effort,
            "mean_seconds_per_call": round(sum(item["seconds"] for item in receipts) / len(receipts), 2) if receipts else None,
            "completion_tokens_total": sum(item["completion_tokens"] for item in receipts
                                           if type(item["completion_tokens"]) is int),
            "question_sha256": [row["question_sha256"] for row in rows]}


def load_questions(index, ids):
    wanted = [line.strip() for line in ids.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not wanted or len(wanted) != len(set(wanted)):
        raise SystemExit("question IDs must be nonempty and unique")
    questions = {}
    with index.open(encoding="utf-8-sig") as source:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            qid = str(row["question_id"])
            if qid in wanted:
                question = row["question"]
                if questions.setdefault(qid, question) != question:
                    raise SystemExit(f"inconsistent text for question ID {qid}")
    if missing := [qid for qid in wanted if qid not in questions]:
        raise SystemExit(f"question IDs missing from input index: {missing}")
    return [(qid, questions[qid]) for qid in wanted]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-index", type=Path, required=True)
    parser.add_argument("--question-ids", type=Path, required=True)
    parser.add_argument("--extract-prompt", type=Path, default=Path(__file__).with_name("extract_prompt.md"))
    parser.add_argument("--audit-prompt", type=Path, default=Path(__file__).with_name("audit_prompt.md"))
    parser.add_argument("--url", required=True)
    parser.add_argument("--model", default="gpt-oss-120b")
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "high"), default="medium")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--max-tokens", type=int, default=16000)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    extract_prompt = args.extract_prompt.read_bytes().decode("utf-8")
    audit_prompt = args.audit_prompt.read_bytes().decode("utf-8")
    model = LocalModel(args.url, args.model, args.timeout, args.max_tokens, args.reasoning_effort)
    questions = load_questions(args.input_index, args.question_ids)
    rows = []
    with (args.output_dir / "results.jsonl").open("w", encoding="utf-8") as results:
        for qid, question in questions:
            row = run_question(qid, question, model, extract_prompt, audit_prompt)
            rows.append(row)
            results.write(json.dumps(row, ensure_ascii=False) + "\n")
            results.flush()
            print(f"{qid} extract={'failed' if row['error'] else 'ok'} "
                  f"audit={'skipped' if row['error'] else 'failed' if row['audit_error'] else 'ok'}", flush=True)
    write_review(args.output_dir / "review.md", rows)
    summary = summarize(rows, extract_prompt, audit_prompt, args.model, args.reasoning_effort)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                                 encoding="utf-8")


if __name__ == "__main__":
    main()
