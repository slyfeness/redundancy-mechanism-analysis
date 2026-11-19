"""Read-only diagnosis of frozen M2 receipts. Raw artifacts stay in the run directory."""

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from difflib import SequenceMatcher
from functools import lru_cache
import hashlib
import html
import json
from pathlib import Path
import re
import unicodedata

from ledger_grpo.ledgercredit.__main__ import load_frozen, rows, selection
from ledger_grpo.ledgercredit.conditions import quote_matches
from ledger_grpo.ledgercredit.evidence_judge import (
    EVIDENCE_PROMPT, PROMPT_VERSION, fed_events, judge_payload, request_once, settle,
)
from ledger_grpo.ledgercredit.stages import observed_texts

VERSION = "bcplus-round4-192109-v2"
SEED = "ledgercredit-m2-diagnosis-20261119"
LIMIT = 60
RESPONSE_LIMIT = 4096
STATUSES = ("supported", "partial", "unknown")
REASONS = {
    "A1": "命中返回元数据", "A2": "反转义或统一 Unicode/引号后匹配",
    "A3": "跨片段拼接", "A4": "在别的引用块中逐字匹配",
    "A5": "当前及其他片段均无逐字匹配", "A6": "超长或有原文证实的截省",
    "A7": "缺摘录或响应不完整", "A8": "通过原始校验",
}
ESCAPES = re.compile(r'\\(u[0-9a-fA-F]{4}|n|r|t|"|\\)')
QUOTES = str.maketrans("‘’‚‛“”„‟", "''''\"\"\"\"")
METADATA = re.compile(r'"\s*(docid|score|rank|snippet|type|text)\s*"\s*:|^\s*[\[\{]\s*"', re.I)


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def write(path, data):
    with path.open("x", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False)
        file.write("\n")


def normalize(text):
    if not isinstance(text, str):
        return ""
    replacements = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}

    def replace(match):
        key = match[1]
        return chr(int(key[1:], 16)) if key.startswith("u") else replacements[key]

    for _ in range(2):
        recovered = ESCAPES.sub(replace, html.unescape(text))
        if recovered == text:
            break
        text = recovered
    return " ".join(unicodedata.normalize("NFKC", text).translate(QUOTES).casefold().split())


def fold(text):
    return " ".join(text.casefold().split())


def norm_match(quote, text):
    return quote_matches(normalize(quote), normalize(text))


def classify(quote, cited, other, incomplete=False):
    """Classify one expected quote, with independent evidence spans in search order."""
    if incomplete or not isinstance(quote, str) or not quote.strip():
        return ["A7"]
    if any(quote_matches(quote, text) for text in cited):
        return ["A8"]
    raw = fold(quote)
    words = raw.split()
    haystacks = [fold(text) for text in cited]
    elsewhere = [fold(text) for text in other]
    pieces = [part.strip() for part in re.split(r"\.{3,}|…", raw) if part.strip()]
    splice = any(" ".join(words[:split]) in left and " ".join(words[split:]) in right
                 for split in range(4, len(words) - 3)
                 for i, left in enumerate(haystacks) for right in haystacks[i + 1:])
    splice |= any(raw in left + " " + right for left, right in zip(haystacks, haystacks[1:]))
    if len(pieces) > 1 and all(len(piece.split()) >= 3 for piece in pieces):
        splice |= (all(any(piece in text for text in haystacks) for piece in pieces) and
                   not any(all(piece in text for piece in pieces) for text in haystacks))
    clipped = (len(pieces) > 1 and all(len(piece.split()) >= 3 for piece in pieces) and
               any(all(piece in text for piece in pieces) for text in haystacks))
    flags = [
        ("A1", bool(METADATA.search(quote))),
        ("A2", any(norm_match(quote, text) for text in cited)),
        ("A3", splice),
        ("A4", any(raw in text for text in elsewhere)),
        ("A6", len(words) > 40 or clipped),
    ]
    return [code for code, present in flags if present] or ["A5"]


def verdicts(receipt):
    try:
        body = json.loads(receipt["raw_output"]["choices"][0]["message"]["content"])
        records = body["verdicts"]
        return [row for row in records if isinstance(row, dict)] if isinstance(records, list) else []
    except (KeyError, IndexError, TypeError, ValueError):
        return []


def compare_receipt(claims, refs, receipt, normalized=False, expected_claims=False):
    decisions = verdicts(receipt)
    active = [] if receipt.get("error") else decisions
    if normalized:
        refs_for_validation = [{**r, "text": normalize(r["text"]),
                                "passages": [normalize(p) for p in r["passages"]]} for r in refs]
        active = [{**r, "quote": normalize(r.get("quote")) or None,
                   **({"prior_partial": [
                       {**p, "quote": normalize(p.get("quote")) or None} if isinstance(p, dict) else p
                       for p in r["prior_partial"]]} if isinstance(r.get("prior_partial"), list) else {})}
                  for r in active]
    else:
        refs_for_validation = refs
    _, checks = settle(claims, refs_for_validation, active)
    index = {r["citation_id"]: r for r in refs}
    quote_rows = []
    for row in decisions:
        prior = row.get("prior_partial")
        sites = [("primary", row)] if row.get("status") in STATUSES[:2] or row.get("quote") else []
        if isinstance(prior, list):
            sites.extend(("prior", item) for item in prior if isinstance(item, dict))
        for role, item in sites:
            cid = item.get("citation_id")
            ref = index.get(cid) if type(cid) is int else None
            cited = ref["passages"] if ref else []
            others = [p for idx, r in index.items() if idx != cid for p in r["passages"]]
            quote = item.get("quote")
            labels = classify(quote, cited, others, bool(receipt.get("error")))
            valid = labels == ["A8"] or (
                not receipt.get("error") and any(norm_match(quote, p) for p in cited))
            quote_rows.append({"id": row.get("id"), "role": role, "citation_id": cid,
                               "unit_id": ref["unit_id"] if ref else None, "quote": quote,
                               "codes": labels, "normalized_pass": valid})
    seen = {r.get("id") for r in decisions if isinstance(r.get("id"), str)}
    if expected_claims:
        missing = [c for c in claims if receipt.get("error") or c["id"] not in seen]
        existing = {r["id"] for r in quote_rows if r["codes"] == ["A7"]}
        quote_rows.extend({"id": c["id"], "role": "missing", "citation_id": None, "unit_id": None,
                           "quote": None, "codes": ["A7"], "normalized_pass": False}
                          for c in missing if c["id"] not in existing)
    return checks, quote_rows


def choose(items, score):
    def order(row):
        return digest(f"{SEED}|{row['trajectory_id']}".encode())

    chosen = []
    # Reserve the two largest rule-only counts even when they also belong to a stratum.
    top = sorted(items, key=lambda row: (-score[row["trajectory_id"]], order(row)))[:2]
    used = {row["trajectory_id"] for row in top}
    strata = (
        ("correct", 3, lambda row: row["submitted"] and row["correct"] is True),
        ("context", 3, lambda row: row["terminal_status"] == "CONTEXT_LIMIT_STOP"),
        ("incorrect", 2, lambda row: row["submitted"] and row["correct"] is False),
    )
    for tag, count, belongs in strata:
        picks = sorted((row for row in items if row["trajectory_id"] not in used and belongs(row)),
                       key=order)[:count]
        if len(picks) != count:
            raise ValueError("not enough eligible training trajectories")
        used.update(row["trajectory_id"] for row in picks)
        chosen.extend({**row, "stratum": tag} for row in picks)
    return chosen + [{**row, "stratum": "most_rule_only"} for row in top]


def read_log_profile(path):
    with path.open(encoding="utf-8", errors="replace") as log:
        engine = next((line for line in log if "Initializing a V1 LLM engine" in line), "")
    limit = re.search(r"max_seq_len=(\d+)", engine)
    version = re.search(r"\(v([\d.]+)\)", engine)
    if not limit or not version:
        raise ValueError("historical running engine context limit was not found")
    return {"max_context": int(limit[1]), "vllm_version": version[1]}


def old_input(claims, refs, usage, limit, created):
    """Rebuild the original JSON and locate the old chunk and snippet starts."""
    from vllm.entrypoints.openai.parser.harmony_utils import (
        get_encoding, get_system_message, parse_chat_inputs_to_harmony_messages, render_for_completion,
    )

    payload = json.dumps(judge_payload(claims, refs), ensure_ascii=False)
    messages = [{"role": "system", "content": EVIDENCE_PROMPT}, {"role": "user", "content": payload}]
    date = datetime.fromtimestamp(created, timezone.utc).date().isoformat()
    conversation = [get_system_message(start_date=date), *parse_chat_inputs_to_harmony_messages(messages)]
    ids = render_for_completion(conversation)
    encoding = get_encoding()
    rendered = encoding.decode_utf8(ids)
    start = rendered.index(payload)

    @lru_cache(maxsize=24000)
    def token_bytes(tid):
        return len(encoding.decode([tid], errors="surrogateescape").encode("utf-8", "surrogateescape"))

    boundaries = [0]
    for tid in ids:
        boundaries.append(boundaries[-1] + token_bytes(tid))
    if boundaries[-1] != len(rendered.encode("utf-8")):
        raise ValueError("Harmony byte offsets did not round trip")

    def token_offset(position):
        return bisect_right(boundaries, len(rendered[:start + position].encode("utf-8"))) - 1

    reconstructed = len(ids)
    served = usage.get("prompt_tokens")
    same_count = served == reconstructed
    locations, cursor = {}, 0
    for ref in refs:
        marker = f'{{"citation_id": {ref["citation_id"]}, "text": '
        block = payload.index(marker, cursor)
        cursor = block + len(marker)
        raw = json.dumps(ref["text"], ensure_ascii=False)
        if payload[cursor:cursor + len(raw)] != raw:
            raise ValueError("legacy citation reconstruction disagrees")
        locations[str(ref["citation_id"])] = {"citation_offset": token_offset(block),
                                             "snippets": {}}
        snippet_cursor = 0
        for snippet in ref["snippets"]:
            escaped = snippet["text"]
            found = []
            for _ in range(4):
                position = raw.find(escaped, snippet_cursor)
                if position >= 0:
                    found.append((position, len(escaped)))
                escaped = json.dumps(escaped, ensure_ascii=False)[1:-1]
            if found:
                position, length = min(found, key=lambda hit: (hit[0], -hit[1]))
                snippet_cursor = position + length
                locations[str(ref["citation_id"])]["snippets"][str(snippet["citation_id"])] = token_offset(
                    cursor + position)
        cursor += len(raw)
    return {"served": served, "reconstructed": reconstructed, "counts_match": same_count,
            "exceeds_context": served > limit if type(served) is int else None,
            "input_truncation": False if same_count and served + RESPONSE_LIMIT <= limit else None,
            "locations": locations}


def prepare(args):
    from transformers import AutoTokenizer

    base = args.root
    original = base / "m2-192109"
    corrected = base / "supplement-m2-192129"
    m1 = base / "supplement-m1-192125"
    labels, training = selection(base.parent / "round4_bcplus" / "selection")
    questions = {row["id"]: row["question"] for row in labels}
    if len(questions) != 50 or not questions.keys() <= training:
        raise ValueError("expected frozen 50-question training pilot")
    conditions = load_frozen(original, questions.keys(), training, VERSION)
    outcome = list(rows(corrected / "trajectory_results.jsonl"))
    if len(outcome) != 399 or any(row["question_id"] not in questions for row in outcome):
        raise ValueError("expected 399 aligned and training-only outcome receipts")
    scores = {row["trajectory_id"]: sum(c["comparison"] == "rule_only" for c in row["checks"])
              for row in rows(corrected / "judge_records.jsonl")}
    picks = choose(outcome, scores)
    selected = {row["trajectory_id"] for row in picks}
    previous = {r["trajectory_id"]: r for r in rows(original / "judge_records.jsonl")
                if r["trajectory_id"] in selected}
    replay = {r["trajectory_id"]: r["checks"] for r in rows(corrected / "judge_records.jsonl")
              if r["trajectory_id"] in selected}
    stages = defaultdict(list)
    for row in rows(m1 / "stages.jsonl"):
        if row["trajectory_id"] in selected:
            stages[row["trajectory_id"]].append(row)

    profile = read_log_profile(base / "judge-192109" / "server.log")
    token = AutoTokenizer.from_pretrained(args.model_path, local_files_only=True)
    model_revision = "config-sha256:" + digest((args.model_path / "config.json").read_bytes())
    profile.update(model_revision=model_revision, prompt_version=PROMPT_VERSION,
                   prompt_sha256=digest(EVIDENCE_PROMPT.encode()))
    output = []
    jobs = []
    for pick in picks:
        tid, qid = pick["trajectory_id"], pick["question_id"]
        archive = previous[tid]
        frozen = conditions[qid]
        if (archive["model"] != "gpt-oss-120b" or archive["model_revision"] != model_revision or
                archive["prompt_version"] != PROMPT_VERSION or archive["conditions_sha256"] != frozen["content_sha256"]):
            raise ValueError("legacy receipt identity mismatch")
        snippets, legacy, units = [], [], defaultdict(list)
        for number, unit, event in fed_events(stages[tid]):
            parts = observed_texts(event)
            refs = [{"citation_id": len(snippets) + i, "unit_id": unit, "legacy_id": number,
                     "text": text, "passages": [text]} for i, text in enumerate(parts, 1)]
            snippets.extend(refs)
            units[unit].extend(refs)
            legacy.append({"citation_id": number, "unit_id": unit, "text": event["return_text"],
                           "passages": parts, "snippets": refs})
        if {str(r["citation_id"]): r["unit_id"] for r in legacy} != archive["citation_units"]:
            raise ValueError("legacy citation index mismatch")
        claims = frozen["conditions"]
        checks, quote_rows = compare_receipt(claims, legacy, archive, expected_claims=True)
        if checks != replay[tid]:
            raise ValueError("historical replay and diagnostic validation differ")
        envelope = archive.get("raw_output") or {}
        usage = envelope.get("usage", {})
        length = old_input(claims, legacy, usage, profile["max_context"], envelope["created"])
        for check in checks:
            check["rule_snippet_id"] = next((
                r["citation_id"] for r in snippets
                if any(quote_matches(e["quote"], r["text"]) for e in
                       next(c["evidence"] for c in claims if c["id"] == check["id"]))), None)
        output.append({**pick, "question_prefix": " ".join(questions[qid].split()[:30]),
                       "claims": claims, "snippets": snippets, "legacy": legacy,
                       "quote_rows": quote_rows, "checks": checks, "legacy_input": length,
                       "v1_error": archive.get("error"), "v1_verdicts": verdicts(archive),
                       "snippet_tokens": sum(len(token.encode(r["text"], add_special_tokens=False)) for r in snippets)})
        ordered = sorted(units)
        blocks = [[r for unit in ordered[i:i + 5] for r in units[unit]]
                  for i in range(0, len(ordered), 5)]
        jobs.append({"tid": tid, "variant": "V2", "block": 0,
                     "payload": judge_payload(claims, snippets)})
        jobs.extend({"tid": tid, "variant": "V3", "block": i,
                     "payload": judge_payload(claims, block)} for i, block in enumerate(blocks))
    if len(jobs) > LIMIT:
        raise ValueError("call plan exceeds the approved diagnostic ceiling")
    args.output.mkdir(mode=0o700, exist_ok=False)
    write(args.output / "plan.json", {"profile": profile, "samples": output, "jobs": jobs})
    print(json.dumps({"planned": Counter(job["variant"] for job in jobs), "samples": [
        {"trajectory_id": s["trajectory_id"], "legacy_prompt_tokens": s["legacy_input"]["served"],
         "reconstructed_tokens": s["legacy_input"]["reconstructed"],
         "snippets": len(s["snippets"]), "snippet_tokens": s["snippet_tokens"],
         "rule_only": scores[s["trajectory_id"]]} for s in output]}), flush=True)


def run(args):
    from ledger_grpo.client import LocalJudge

    path = args.output
    plan = read(path / "plan.json")
    if len(plan["jobs"]) > LIMIT or len(plan["samples"]) != 10:
        raise ValueError("invalid diagnostic call budget")
    client = LocalJudge(args.url, "gpt-oss-120b", cache_size=0)
    with client.opener.open(args.url.rstrip("/") + "/models", timeout=10) as response:
        models = json.load(response)["data"]
    limit = next(row["max_model_len"] for row in models if row["id"] == "gpt-oss-120b")
    if limit != plan["profile"]["max_context"]:
        raise ValueError("new and historical serving context limits differ")

    def call(job):
        try:
            _, raw, error = request_once(args.url, "gpt-oss-120b", EVIDENCE_PROMPT,
                                         job["payload"], max_tokens=RESPONSE_LIMIT)
        except Exception as exc:
            raw, error = None, type(exc).__name__
        return {"tid": job["tid"], "variant": job["variant"], "block": job["block"],
                "raw_output": raw, "error": error}

    write(path / "service.json", {"model": "gpt-oss-120b", "max_context": limit})
    with (path / "requests.jsonl").open("x", encoding="utf-8") as file:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for count, result in enumerate(pool.map(call, plan["jobs"]), 1):
                file.write(json.dumps(result, ensure_ascii=False) + "\n")
                file.flush()
                print(json.dumps({"completed": count, "variant": result["variant"],
                                  "error": result["error"]}), flush=True)


def quote_value(records, cid):
    return next((r for r in records if r.get("id") == cid), {})


def grouped_refs(block, snippets):
    index = {r["citation_id"]: r for r in snippets}
    return [index[r["citation_id"]] for r in block["payload"]["citations"]]


def measure(samples, receipts, jobs):
    result, by_sample = {}, {}
    request_index = {(r["tid"], r["variant"], r["block"]): r for r in receipts}
    for version in ("V1", "V2", "V3"):
        total = Counter()
        for sample in samples:
            tid = sample["trajectory_id"]
            claims = sample["claims"]
            leaders = {}
            if version == "V1":
                checks = sample["checks"]
                quotes = sample["quote_rows"]
                old_usage = sample["legacy_input"]["served"]
                if type(old_usage) is int:
                    total.update(input_tokens=old_usage, token_receipts=1)
                total.update(archived=1, errors=bool(sample["v1_error"]),
                             quote_total=len(quotes), quote_pass=sum(q["codes"] == ["A8"] for q in quotes),
                             normalized_pass=sum(q["normalized_pass"] for q in quotes))
                for check in checks:
                    if check["judge_unit"] is not None:
                        leaders[check["id"]] = (check["judge_unit"],
                                                 quote_value(sample["v1_verdicts"], check["id"]))
            else:
                selected = [j for j in jobs if j["tid"] == tid and j["variant"] == version]
                for block in selected:
                    receipt = request_index[(tid, version, block["block"])]
                    refs = grouped_refs(block, sample["snippets"])
                    checks, quotes = compare_receipt(claims, refs, receipt, normalized=True, expected_claims=True)
                    usage = (receipt.get("raw_output") or {}).get("usage", {}).get("prompt_tokens")
                    if type(usage) is int:
                        total.update(input_tokens=usage, token_receipts=1)
                    total.update(calls=1, errors=bool(receipt["error"]), quote_total=len(quotes),
                                 quote_pass=sum(q["normalized_pass"] for q in quotes))
                    for check in checks:
                        unit, cid = check["judge_unit"], check["id"]
                        raw = quote_value(verdicts(receipt), cid)
                        if unit is not None and (cid not in leaders or unit < leaders[cid][0]):
                            leaders[cid] = (unit, raw)
                        by_sample.setdefault((tid, version, cid), []).append(
                            {"block": block["block"], "status": raw.get("status", "缺失"),
                             "citation_id": raw.get("citation_id"), "quote": raw.get("quote"),
                             "judge_unit": unit, "error": receipt["error"]})
            for check in sample["checks"]:
                cid = check["id"]
                rule, judge = check["rule_unit"], leaders.get(cid, (None, {}))[0]
                category = ("both" if rule is not None and judge is not None else
                            "only_rule" if rule is not None else "only_judge" if judge is not None else "neither")
                total[category] += 1
                total["supported"] += judge is not None
                total["same_first"] += category == "both" and rule == judge
                by_sample[(tid, version, cid, "leader")] = leaders.get(cid, (None, {}))
        result[version] = dict(total)
    return result, by_sample

def rule_only_rows(samples):
    details = []
    for sample in samples:
        snippets = {r["citation_id"]: r for r in sample["snippets"]}
        measured = sample["legacy_input"]
        for check in sample["checks"]:
            if check["comparison"] != "rule_only":
                continue
            snippet = snippets[check["rule_snippet_id"]]
            if snippet["unit_id"] != check["rule_unit"]:
                raise ValueError("rule-only first unit mismatch")
            block = str(snippet["legacy_id"])
            match = measured["locations"][block]
            verdict = quote_value(sample["v1_verdicts"], check["id"])
            quote = next((row for row in sample["quote_rows"]
                          if row["id"] == check["id"] and row["role"] == "primary"), None)
            failures = [row["codes"] for row in sample["quote_rows"] if row["id"] == check["id"]]
            details.append({"trajectory_id": sample["trajectory_id"], "id": check["id"],
                            "unit_id": check["rule_unit"], "rule_snippet_id": snippet["citation_id"],
                            "v1_citation_for_rule": snippet["legacy_id"],
                            "v1_citation_used": verdict.get("citation_id"),
                            "same_v1_citation": verdict.get("citation_id") == snippet["legacy_id"],
                            "v1_status": verdict.get("status", "缺失"),
                            "v1_quote_codes": quote["codes"] if quote else [],
                            "v1_all_quote_codes": failures,
                            "v1_quote_passed": check["quote_passed"],
                            "v1_schema_valid": check["schema_valid"],
                            "v1_joint_quote_order_failed": (any(row["role"] == "prior"
                                and row["id"] == check["id"] for row in sample["quote_rows"])
                                and not check["quote_passed"]
                                and failures and all(codes == ["A8"] for codes in failures)),
                            "v1_error": sample["v1_error"],
                            "snippet_token_offset": match["snippets"].get(str(snippet["citation_id"])),
                            "citation_token_offset": match["citation_offset"],
                            "v1_prompt_tokens": measured["served"],
                            "input_truncation": measured["input_truncation"],
                            "input_exceeds_limit": measured["exceeds_context"]})
    return details


def excerpt(text, focus):
    """Keep an original word span around the closest lexical overlap."""
    if not text:
        return "（无有效引用片段）"
    words = list(re.finditer(r"\S+", text))
    if not words:
        return "（空片段）"
    wanted = normalize(focus).split()
    hay = [normalize(word[0]) for word in words]
    match = SequenceMatcher(None, hay, wanted, autojunk=False).find_longest_match()
    left = max(0, match.a - 42) if match.size else 0
    right = min(len(words), match.a + match.size + 42) if match.size else min(len(words), 42)
    return ("… " if left else "") + text[words[left].start():words[right - 1].end()] + (
        " …" if right < len(words) else "")


def best_snippet(candidates, focus):
    wanted = set(normalize(focus).split())
    return max(candidates, key=lambda p: (norm_match(focus, p),
                                         len(wanted & set(normalize(p).split()))), default="")


def code_text(value):
    return "<code>" + html.escape(str(value) if value else "（无）").replace("\n", "<br>") + "</code>"


def case_heading(sample, cid, unit):
    return (f"- ID {sample['trajectory_id']} / unit {unit if unit is not None else '缺失'} / "
            f"断言 {cid} / query_id {sample['question_id']}\n"
            f"  - 题面前 30 词 {code_text(sample['question_prefix'])}")


def review_packet(samples, rule_only, measurements):
    by_tid = {s["trajectory_id"]: s for s in samples}
    lines = ["# M2 Judge 核验包", "",
             "V1 引用编号标识工具返回，V2/V3 编号标识单个可见片段。各条示例只展示附近原文。",
             "原文没有词面交集时展示片段开头。此包用于核验语义，保留程序判定的边界。", "",
             "## A 摘录校验分类", ""]
    for code, label in REASONS.items():
        lines.extend((f"### {code} {label}", ""))
        candidates = [(s, row) for s in samples for row in s["quote_rows"] if code in row["codes"]]
        candidates.sort(key=lambda pair: (pair[1]["codes"][0] != code, digest(
            f"{SEED}|{pair[0]['trajectory_id']}|{pair[1]['id']}|{pair[1]['role']}".encode())))
        for sample, row in candidates[:3]:
            ref = next((r for r in sample["legacy"] if r["citation_id"] == row["citation_id"]), {})
            quote = row["quote"]
            passage = best_snippet(ref.get("passages", []), quote)
            lines.extend((case_heading(sample, row["id"], row["unit_id"]),
                          f"  - 引用 {row['citation_id']}，分类 {' / '.join(row['codes'])}",
                          f"  - Judge 摘录 {code_text(quote)}",
                          f"  - 引用片段 {code_text(excerpt(passage, quote))}"))
            if "A4" in row["codes"]:
                alternate = next(((r, t) for r in sample["legacy"] if r["citation_id"] != row["citation_id"]
                                  for t in r["passages"] if fold(quote) in fold(t)), None)
                if alternate:
                    r, t = alternate
                    lines.append(f"  - 匹配的另一个引用 {r['citation_id']} / unit {r['unit_id']} "
                                 f"{code_text(excerpt(t, quote))}")
        lines.append("")
    lines.extend(("## B 仅规则支持", ""))
    example_order = sorted(rule_only, key=lambda row: digest(
        f"{SEED}|B|{row['trajectory_id']}|{row['id']}".encode()))
    for item in example_order[:10]:
        tid, cid = item["trajectory_id"], item["id"]
        sample = by_tid[tid]
        claim = next(c for c in sample["claims"] if c["id"] == cid)
        snippet = next(r for r in sample["snippets"] if r["citation_id"] == item["rule_snippet_id"])
        focus = next(e["quote"] for e in claim["evidence"] if quote_matches(e["quote"], snippet["text"]))
        lines.extend((case_heading(sample, cid, item["unit_id"]),
                      f"  - 冻结断言 {code_text(claim['text'])}",
                      f"  - 规则命中片段 {snippet['citation_id']}，V1 引用 {snippet['legacy_id']}，"
                      f"token 偏移 {item['snippet_token_offset']} {code_text(excerpt(snippet['text'], focus))}"))
        raw = quote_value(sample["v1_verdicts"], cid)
        lines.append(f"  - V1 {item['v1_status']} / 引用 {raw.get('citation_id')} / "
                     f"{item['v1_quote_codes']} / {code_text(raw.get('quote'))}")
        for variant in ("V2", "V3"):
            for row in measurements.get((tid, variant, cid), []):
                lines.append(f"  - {variant} 块 {row['block']} / {row['status']} / "
                             f"校验后支持 unit {row['judge_unit']} / 引用 {row['citation_id']} / "
                             f"{code_text(row['quote'])}")
    lines.extend(("", "## C 仅 V2 或 V3 支持", ""))
    candidates = []
    for sample in samples:
        tid = sample["trajectory_id"]
        for check in sample["checks"]:
            if check["rule_unit"] is not None:
                continue
            cid = check["id"]
            positive = {v: measurements[tid, v, cid, "leader"] for v in ("V2", "V3")
                        if measurements[tid, v, cid, "leader"][0] is not None}
            if positive:
                candidates.append((sample, cid, positive))
    candidates.sort(key=lambda case: digest(f"{SEED}|C|{case[0]['trajectory_id']}|{case[1]}".encode()))
    for sample, cid, positive in candidates[:10]:
        unit = min(row[0] for row in positive.values())
        claim = next(c for c in sample["claims"] if c["id"] == cid)
        lines.extend((case_heading(sample, cid, unit), f"  - 冻结断言 {code_text(claim['text'])}"))
        for variant, (unit, raw) in positive.items():
            evidence = [raw, *(raw.get("prior_partial") or [])]
            for cite in evidence:
                snippet = next(r for r in sample["snippets"] if r["citation_id"] == cite["citation_id"])
                lines.append(f"  - {variant} unit {snippet['unit_id']} / 片段 {cite['citation_id']} / "
                             f"摘录 {code_text(cite['quote'])} / {code_text(excerpt(snippet['text'], cite['quote']))}")
    return "\n".join(lines).strip() + "\n"


def rate(n, d):
    return f"{n}/{d} ({100*n/d:.1f}%)" if d else f"{n}/{d}（无分母）"


def public_report(plan, stats, rule_only, new_profile, job):
    samples = plan["samples"]
    quote_rows = [r for sample in samples for r in sample["quote_rows"]]
    primary = Counter(r["codes"][0] for r in quote_rows)
    any_hit = Counter(code for r in quote_rows for code in r["codes"])
    main_failure = max((code for code in REASONS if code != "A8"), key=lambda code: primary[code])
    limits = [s["legacy_input"] for s in samples]
    located = [r["snippet_token_offset"] for r in rule_only if r["snippet_token_offset"] is not None]
    status = Counter(r["v1_status"] if r["v1_status"] in STATUSES else "缺失" for r in rule_only)
    raw_supports = [r for r in rule_only if r["v1_status"] == "supported"]
    same_block = sum(r["same_v1_citation"] for r in raw_supports)
    pair_quote_codes = Counter(code for row in raw_supports for codes in row["v1_all_quote_codes"]
                               for code in codes[:1])
    old_profile = plan["profile"]
    cap = old_profile["max_context"]
    offsets = f"{min(located):,}–{max(located):,}" if located else "无"
    harm = sum(v["counts_match"] for v in limits)
    no_cut = sum(v["input_truncation"] is False for v in limits)
    top_version = max(("V2", "V3"), key=lambda v: (stats[v]["both"], stats[v]["same_first"],
                                                  -stats[v]["input_tokens"]))
    lines = [
        "# M2 Judge 小样本诊断", "",
        f"**[已验证]** 旧摘录失败的首要类别为 **{main_failure} {REASONS[main_failure]}**，"
        f"占失败的 {rate(primary[main_failure], len(quote_rows)-primary['A8'])}。"
        f"10 条旧请求中 {no_cut} 条确认输入完整。",
        "",
        f"只读训练集 10 条，种子 {SEED}。模型 gpt-oss-120b "
        f"{old_profile['model_revision']}，提示词 {old_profile['prompt_version']} "
        f"（{old_profile['prompt_sha256'][:12]}）。"
        f"V1/V2–V3 的 vLLM 分别为 {old_profile['vllm_version']}/{new_profile['vllm_version']}，"
        f"最大上下文均为 {cap:,} token。新增请求作业 {job}。",
        "",
        "| 轨迹 ID | 终止方式 | 片段数 | 片段 token | V1 输入 token |",
        "|---|---|---:|---:|---:|",
    ]
    lines.extend(f"| {s['trajectory_id']} | {s['terminal_status']} | {len(s['snippets'])} | "
                 f"{s['snippet_tokens']:,} | {s['legacy_input']['served']:,} |" for s in samples)
    lines.extend((
        "",
        "| A 类别 | " + " | ".join(REASONS) + " |",
        "|---|" + "---:|" * len(REASONS),
        "| 主类 | " + " | ".join(str(primary[code]) for code in REASONS) + " |",
        "| 多选 | " + " | ".join(str(any_hit[code]) for code in REASONS) + " |",
        "",
        f"**[已验证]** 按应校验摘录槽计，规范化使 V1 从 {rate(primary['A8'], len(quote_rows))} "
        f"变为 {rate(sum(r['normalized_pass'] for r in quote_rows), len(quote_rows))}。"
        "A7 包含缺回执的应检项。多选允许交叉。",
        "",
        f"**B [已验证]** 仅规则支持 {len(rule_only)} 对。V1 原状态 supported / partial / unknown / 缺失"
        f"依次为 {' / '.join(str(status[s]) for s in (*STATUSES, '缺失'))}。"
        f"其中 {same_block}/{len(raw_supports)} 个 supported 引用了规则命中的返回块。"
        "这些 supported 的摘录主类计数为 " +
        ("、".join(f"{code} {number}" for code, number in sorted(pair_quote_codes.items())) or "0") +
        f"。找到 {len(located)}/{len(rule_only)} 个规则片段的原输入偏移（{offsets} token）。"
        f"Harmony 重建与服务用量一致 {harm}/10，旧输入超限 "
        f"{sum(v['exceeds_context'] is True for v in limits)}/10。"
        "旧请求未传截断参数，上下文余量包含 4,096 个输出 token。",
        "",
        "| 版本 | 摘录校验 | supported | 同 / 仅 Judge / 仅规则 | 首次单元一致 | 新调用 / 失败 | 输入 token |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ))
    for version, v in stats.items():
        lines.append(f"| {version} | {rate(v['quote_pass'],v['quote_total'])} | {v['supported']} | "
                     f"{v['both']} / {v['only_judge']} / {v['only_rule']} | "
                     f"{rate(v['same_first'],v['both'])} | {v.get('calls',0)} / "
                     f"{v['errors'] if version != 'V1' else 0} | {v['input_tokens']:,}"
                     f" ({v['token_receipts']}/{v.get('archived',v.get('calls',0))}) |")
    lines.extend((
        "",
        f"**[推断]** 优先用 {top_version} 继续校准。按与规则共同支持数、首次单元一致数、输入成本依次比较。"
        "校验前做反转义、HTML 实体还原、NFKC、引号和空白归一。保留单片段逐字匹配及 40 词上限。"
        "规则路径只用于核验，暂不参与结算。本组定向纳入高差异轨迹，规则命中的语义充分性和分块跨片段联合支持仍待确认。",
    ))
    return "\n".join(lines) + "\n"


def report(args):
    path = args.output
    run_path = args.run_dir or path
    plan = read(path / "plan.json")
    if plan["jobs"] != read(run_path / "plan.json")["jobs"]:
        raise ValueError("executed calls and reconstructed plan differ")
    receipts = list(rows(run_path / "requests.jsonl"))
    expected = {(r["tid"], r["variant"], r["block"]) for r in plan["jobs"]}
    actual = {(r["tid"], r["variant"], r["block"]) for r in receipts}
    if expected != actual or len(expected) != len(receipts) or len(receipts) > LIMIT:
        raise ValueError("unexpected or missing diagnostic receipt")
    new_profile = read_log_profile(run_path / "server.log")
    if new_profile["max_context"] != read(run_path / "service.json")["max_context"]:
        raise ValueError("service and engine contexts disagree")
    stats, measurements = measure(plan["samples"], receipts, plan["jobs"])
    details = rule_only_rows(plan["samples"])
    for name, value in (("REPORT.md", public_report(plan, stats, details, new_profile, args.job_id)),
                        ("REVIEW_PACKET.md", review_packet(plan["samples"], details, measurements))):
        with (path / name).open("x", encoding="utf-8") as file:
            file.write(value)
    with (path / "RULE_ONLY_DETAILS.jsonl").open("x", encoding="utf-8") as file:
        for detail in details:
            file.write(json.dumps(detail, ensure_ascii=False) + "\n")

    quote_rows = [row for sample in plan["samples"] for row in sample["quote_rows"]]
    summary = {"versions": stats, "model": plan["profile"], "new_service": new_profile,
               "a_primary": dict(Counter(row["codes"][0] for row in quote_rows)),
               "a_all": dict(Counter(code for row in quote_rows for code in row["codes"])),
               "rule_status": dict(Counter(row["v1_status"] for row in details)),
               "v1_token_counts_match": sum(s["legacy_input"]["counts_match"] for s in plan["samples"]),
               "v1_untruncated": sum(s["legacy_input"]["input_truncation"] is False for s in plan["samples"]),
               "rule_offsets_located": sum(r["snippet_token_offset"] is not None for r in details),
               "rule_only": len(details), "new_calls": len(receipts), "heldout_read": 0}
    write(path / "DIAGNOSIS.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "run", "report"))
    parser.add_argument("--root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--url")
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--job-id", type=int)
    args = parser.parse_args()
    if args.mode == "report":
        report(args)
    else:
        {"prepare": prepare, "run": run}[args.mode](args)


if __name__ == "__main__":
    main()
