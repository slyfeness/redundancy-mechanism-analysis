#!/usr/bin/env python3
"""Index the historical 100 × 4 BrowseComp-Plus run on a Slurm CPU node."""

import argparse
from collections import Counter, defaultdict
from difflib import SequenceMatcher
import hashlib
import itertools
import json
from pathlib import Path
import re
import unicodedata


NATURAL = "BrowseCompPlus_RANDOM100_T1_N4_DUALACTOR"
SEMANTIC = "BrowseCompPlus_Codex_semantic_review_20261019"
RETRIEVER = Path("GPU_JOB_150131/retriever_gpu1")
OLD = {
    "token15_preview20": ("SUCCESS100_SWAP_TOKEN15_PREVIEW_V1", "INPUT_MANIFEST.json", "stages.jsonl"),
    "token15_remaining80": ("SUCCESS100_SWAP_TOKEN15_REMAINING80_ABLATION_V1", "INPUT_MANIFEST.json", "STAGES.jsonl"),
    "token15_deletion20": ("SUCCESS100_SWAP_TOKEN15_ABLATION20_V1", "SOURCE_AUDIT.json", "BRANCH_RESULTS.jsonl"),
    "token15_deletion80": ("SUCCESS100_SWAP_TOKEN15_REMAINING80_ABLATION_V1", "SOURCE_AUDIT.json", "BRANCH_RESULTS.jsonl"),
}
LABELS = {"CORRECT": "C", "INCORRECT": "W", "NO_FINAL": "N", "UNCERTAIN": "UNCERTAIN"}
BUDGET_STOPS = {"CONTEXT_LIMIT_STOP", "GENERATION_LENGTH_STOP", "SAFETY_CEILING_STOP"}


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else digest_stream(source)


def digest_stream(source):
    result = hashlib.sha256()
    for block in iter(lambda: source.read(1024 * 1024), b""):
        result.update(block)
    return result.hexdigest()


def write(path, payload):
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(payload, encoding="utf-8", newline="\n")
    temp.replace(path)


def write_json(path, value):
    write(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_jsonl(path, rows):
    write(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def unique(rows, key):
    index = {}
    for row in rows:
        value = str(row[key])
        if value in index:
            raise ValueError(f"duplicate {key}")
        index[value] = row
    return index


def normalize_question(question):
    return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", question).casefold()))


def close_questions(first, second):
    if first == second:
        return True
    if not first or not second or min(len(first), len(second)) / max(len(first), len(second)) < 0.80:
        return False
    first_tokens, second_tokens = set(first.split()), set(second.split())
    return (len(first_tokens & second_tokens) / len(first_tokens | second_tokens) >= 0.82
            and SequenceMatcher(None, first, second, autojunk=False).ratio() >= 0.92)


def question_groups(questions):
    canonical = {qid: normalize_question(question) for qid, question in questions.items()}
    membership = {qid: qid for qid in questions}
    for first, second in itertools.combinations(sorted(questions), 2):
        if close_questions(canonical[first], canonical[second]):
            keep, discard = sorted((membership[first], membership[second]))
            for qid, group in membership.items():
                if group == discard:
                    membership[qid] = keep
    groups = defaultdict(list)
    for qid in sorted(questions):
        groups[membership[qid]].append(qid)
    return list(groups.values())


def split_questions(questions, seed):
    groups = question_groups(questions)
    groups.sort(key=lambda group: sha(f"bcp-phase1-split|{seed}|" + "|".join(group)))
    labels = ("dev", "calibration", "audit")
    calibration = len(questions) // 5
    capacity = (len(questions) - 2 * calibration, calibration, calibration)
    states = {(0, 0, 0): ()}
    for group in groups:
        next_states = {}
        for counts, assignment in states.items():
            for i, maximum in enumerate(capacity):
                changed = list(counts)
                changed[i] += len(group)
                if changed[i] <= maximum:
                    next_states.setdefault(tuple(changed), (*assignment, i))
        states = next_states
    if capacity not in states:
        raise ValueError("near-duplicate groups prevent the requested question-level split")
    return {qid: labels[label] for group, label in zip(groups, states[capacity]) for qid in group}


def result_of(judgment, stop):
    result = LABELS[judgment]
    if stop == "MODEL_FINAL_STOP":
        if result == "N":
            raise ValueError("formal final lacks a semantic decision")
        return result, {"C": 1, "W": 0, "UNCERTAIN": None}[result]
    if result != "N":
        raise ValueError("judgment requires a formal final")
    return result, 0 if stop in BUDGET_STOPS or stop == "EMPTY_MODEL_STOP" else None


def historical_environment(root):
    config_path = root / "config_manifest.json"
    alignment_path = root / RETRIEVER / "INDEX_ALIGNMENT_RESULT.json"
    smoke_path = root / RETRIEVER / "RETRIEVAL_SMOKE.json"
    server_path = root / "phase10_retriever_adapted.py"
    config, alignment, smoke = map(read, (config_path, alignment_path, smoke_path))
    retriever = config["retriever"]
    identity = {
        "encoder_revision": retriever["revision"],
        "index_revision": retriever["index_revision"],
        "corpus_revision": retriever["corpus_revision"],
        "snippet_tokenizer_revision": retriever["snippet_tokenizer_revision"],
        "runtime_config_sha256": digest(config_path),
        "search_adapter_sha256": digest(server_path),
        "retrieval_alignment_sha256": digest(alignment_path),
        "retrieval_smoke_sha256": digest(smoke_path),
        "recorded_run": str(smoke["job_id"]),
    }
    stable = (
        alignment["status"] == "PASS" and smoke.get("status") == "RETRIEVAL_SMOKE_PASS"
        and alignment.get("job_id") == smoke.get("job_id")
        and all(alignment.get(key) == identity[key] for key in ("encoder_revision", "index_revision", "corpus_revision"))
        and len(smoke["records"]) == smoke["query_count"] >= 3
        and all(len(row["repeats"]) == smoke["repeats_per_query"] >= 3
                and row["deterministic_exact_docid_order_and_rendering"]
                and len({rep["rendering_sha256"] for rep in row["repeats"]}) == 1 for row in smoke["records"])
    )
    return config, identity, stable


def audit_trace(trace, terminal, task, question, config):
    meta, rounds, events = trace["metadata"], trace["rounds"], trace["tool_events"]
    status = terminal["status"]
    if meta.get("terminal_status") != status or len(rounds) != terminal["actor_calls"] or len(events) != terminal["search_calls"]:
        raise ValueError("terminal differs from raw trajectory")
    if meta.get("task") != task:
        raise ValueError("raw task identity differs from frozen input")
    if not rounds or rounds[0]["actor_visible_messages"] != [{"role": "user", "content": question}]:
        raise ValueError("raw question mismatch")
    if (meta.get("model_revision"), meta.get("tokenizer_revision")) != (config["model_revision"], config["tokenizer_revision"]):
        raise ValueError("model/tokenizer revision discrepancy")
    native_rounds = sum(
        row["response_received"] and row["token_accounting"].get("exact_prompt_token_ids_equal") is True
        and isinstance(row["token_accounting"].get("prompt_token_ids"), list)
        and isinstance(row["token_accounting"].get("completion_token_ids"), list)
        and len(row["token_accounting"]["completion_token_ids"]) == row["completion_tokens"]
        for row in rounds
    )
    repeated_pairs, different_returns = 0, 0
    prior = defaultdict(set)
    multiple_calls = Counter(event["round_id"] for event in events)
    for event in events:
        tool = event.get("tool_name")
        args = json.loads(event.get("exact_arguments", "{}"))
        if (tool != "search-server-search" or set(args) != {"query"} or not isinstance(args["query"], str)
                or not event.get("return_utc") or (event.get("raw_mcp_response") or {}).get("isError") is not False):
            continue
        response = json.dumps(event["exact_result"], ensure_ascii=False, sort_keys=True)
        key = args["query"]
        response_hash = sha(response)
        if prior[key]:
            if response_hash in prior[key]:
                repeated_pairs += 1
            else:
                different_returns += 1
        prior[key].add(response_hash)
    return native_rounds, len(rounds), sum(count > 1 for count in multiple_calls.values()), repeated_pairs, different_returns


def old_assets(reports, natural_hashes):
    states, private = {}, []
    legacy_matches = set()
    for role, relative in OLD.items():
        subdir, *names = relative
        receipts = []
        for name in names:
            path = reports / subdir / name
            receipt = {"name": name, "status": "present" if path.is_file() else "missing"}
            if path.is_file():
                receipt.update(sha256=digest(path), bytes=path.stat().st_size)
            receipts.append(receipt)
            private.append({"role": role, "path": str(path), **receipt})
        directory = reports / subdir
        source = directory / "INPUT_MANIFEST.json"
        if role.startswith("token15_preview") or role.startswith("token15_remaining"):
            hashes = set()
            if source.is_file():
                for item in read(source).get("sources", []):
                    if item.get("source_sha256"):
                        hashes.add(item["source_sha256"])
            matches = hashes & natural_hashes
            states[role] = {"files": receipts, "enumerated_source_hashes": len(hashes), "exact_source_hash_matches": len(matches)}
            legacy_matches |= matches
        else:
            states[role] = {"files": receipts}
    return states, private, legacy_matches


def build(reports, output, seed):
    root, semantic_root = reports / NATURAL, reports / SEMANTIC
    source_paths = {
        "sample_manifest": root / "sample_manifest.json",
        "task_manifest": root / "task_manifest.json",
        "evaluation_ledger": root / "per_run_results.jsonl",
        "semantic_ledger": semantic_root / "semantic_results_400.json",
        "historical_mechanical_qa": root / "MECHANICAL_QA.json",
        "historical_final_audit": semantic_root / "RAW_FINAL_AUDIT_SUMMARY.json",
        "historical_actor_completion": root / "ACTOR_COMPLETE.json",
    }
    inputs = {role: {"name": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
              for role, path in source_paths.items()}
    samples = unique(read(source_paths["sample_manifest"])["selected"], "query_id")
    tasks = unique(read(source_paths["task_manifest"])["tasks"], "run_id")
    semantic = unique(read(source_paths["semantic_ledger"])["rows"], "run_id")
    final_audit = unique(read(source_paths["historical_final_audit"])["rows"], "run_id")
    results = unique((json.loads(line) for line in source_paths["evaluation_ledger"].read_bytes().splitlines()), "run_id")
    expected = set(tasks)
    groups = Counter(str(task["query_id"]) for task in tasks.values())
    if len(samples) != 100 or len(expected) != 400 or set(groups) != set(samples) or set(groups.values()) != {4}:
        raise ValueError("frozen allocation is not 100 questions × 4")
    if len({(str(task["query_id"]), task["repetition_id"]) for task in tasks.values()}) != 400:
        raise ValueError("repetition IDs are not unique within question")
    if len({task["seed"] for task in tasks.values()}) != 400 or expected != set(semantic) or expected != set(results) or expected != set(final_audit):
        raise ValueError("manifest, seeds, and independent evaluation do not align")
    raw_paths = {path.name for path in (root / "trajectories").iterdir() if path.is_dir()}
    questions = {qid: row["question"] for qid, row in samples.items()}
    splits = split_questions(questions, seed)
    near_groups = question_groups(questions)
    config, environment, stable_retriever = historical_environment(root)
    environment_id = sha(json.dumps(environment, sort_keys=True))
    index, failures, observed = [], [], Counter()
    for run_id, task in tasks.items():
        question_id = str(task["query_id"])
        question = questions[question_id]
        relative = Path("trajectories") / run_id
        path = root / relative / "trajectory.json"
        seal = root / relative / "TERMINAL.json"
        base = {
            "path": str(path), "question": question, "question_id": question_id, "trajectory_id": run_id,
            "split": splits[question_id], "environment": environment_id,
            "deterministic_tools": ["search-server-search"] if stable_retriever else [],
            "model": "Qwen3.5-9B", "model_version": config["model_revision"],
            "tokenizer_version": config["tokenizer_revision"], "source_seed": task["seed"],
        }
        independent = semantic[run_id]
        row = results[run_id]
        try:
            data = path.read_bytes()
            raw_hash = sha(data)
            terminal = read(seal)
            trace = json.loads(data)
            if any(terminal.get(key) != value for key, value in task.items()):
                raise ValueError("sealed task identity differs")
            final_record = final_audit[run_id]
            if not all((terminal["trajectory"]["sha256"] == raw_hash,
                        terminal["trajectory"]["bytes"] == len(data), row["trajectory"]["sha256"] == raw_hash,
                        independent["original_trajectory_sha256"] == raw_hash,
                        final_record["sha256"] == raw_hash, final_record["sha_match"], final_record["final_matches_raw"])):
                raise ValueError("raw source SHA-256/final receipt mismatch")
            if (task["question_sha256"] != sha(question) or samples[question_id]["question_sha256"] != sha(question)
                    or row["status"] != terminal["status"] or independent["status"] != terminal["status"]
                    or any(independent.get(key) != value for key, value in task.items())):
                raise ValueError("question identity/terminal outside frozen manifest")
            raw_final = (trace["rounds"][-1].get("content") or "") if terminal["status"] == "MODEL_FINAL_STOP" else ""
            if raw_final != independent["final"] or raw_final != row["final"]:
                raise ValueError("independent evaluation is for a different final")
            result, value = result_of(independent["judgment"], terminal["status"])
            native, rounds, parallel, repeats, changed = audit_trace(trace, terminal, task, question, config)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            failures.append({"trajectory_id": run_id, "question_id": question_id,
                             "split": splits[question_id], "reason": str(exc)})
            continue
        observed.update(validated_trajectories=1, model_rounds=rounds, native_id_rounds=native,
                        parallel_rounds=parallel, tool_events=len(trace["tool_events"]),
                        repeated_equal_search_returns=repeats, repeated_changed_search_returns=changed)
        index.append({
            **base, "sha256": raw_hash, "result": result, "Y": value, "termination_reason": terminal["status"],
            "result_source": {"kind": "historical_independent_answer_review",
                              "sha256": inputs["semantic_ledger"]["sha256"], "record_id": run_id},
            "native_ids": "present" if rounds == native else "incomplete",
        })
    old, private_old, matches = old_assets(reports, {row["sha256"] for row in index})
    split_manifest = [{"question_id": qid, "split": splits[qid], "near_duplicate_group_id": sha("|".join(group)),
                       "question_sha256": sha(questions[qid])} for group in near_groups for qid in group]
    output.mkdir(parents=True, exist_ok=False)
    write_jsonl(output / "input_index.jsonl", index)
    write_jsonl(output / "split_manifest.jsonl", split_manifest)
    write_jsonl(output / "inventory_failures.jsonl", failures)
    write_json(output / "old_assets.json", private_old)
    inventory = {
        "schema_version": "1.0", "dataset": "BrowseComp-Plus", "source_actor_job": 150131,
        "status": "READY" if not failures and raw_paths == expected else "BLOCKED_DATA",
        "expected_questions": len(samples), "expected_trajectories": len(expected),
        "missing_trajectory_directories": len(expected - raw_paths),
        "extra_trajectory_directories": len(raw_paths - expected), "failed_trajectories": len(failures),
        "result_counts": dict(Counter(row["result"] for row in index)),
        "unusable_results": sum(row["Y"] is None for row in index),
        "terminal_counts": dict(Counter(row["termination_reason"] for row in index)),
        "split": {"seed": seed, "counts": dict(Counter(splits.values())),
                  "near_duplicate_groups": sum(len(group) > 1 for group in near_groups),
                  "rule": "NFKC/casefold/word normalization; exact or character similarity >=.92 and token Jaccard >=.82; connected components kept together"},
        "trace_coverage": dict(observed), "source_artifacts": inputs, "legacy_assets": old,
        "inventory_scope": "historical natural traces and read-only retained legacy receipts",
        "legacy_mapping": {"exact_source_hash_matches": len(matches),
                           "criteria": "Historical same-question branches require exact source byte identity and independently checked spans before association."},
        "actor_model_revision": config["model_revision"], "actor_tokenizer_revision": config["tokenizer_revision"],
        "environment_id": environment_id, "environment_provenance": environment,
        "search_determinism": "empirical_fixed_run_smoke" if stable_retriever else "unverified",
        "judge_environment": {"historical_model": "gpt-oss-120b", "historical_successful_slurm_job": 183358,
                              "endpoint": "loopback", "runtime_model_probe_required": True},
        "private_output_sha256": {name: digest(output / name) for name in ("input_index.jsonl", "split_manifest.jsonl",
                                                                         "old_assets.json", "inventory_failures.jsonl")},
    }
    write_json(output / "inventory.json", inventory)
    print(json.dumps({k: inventory[k] for k in ("status", "expected_questions", "expected_trajectories",
                                               "failed_trajectories", "result_counts", "trace_coverage", "legacy_mapping")},
                     ensure_ascii=False), flush=True)
    return not failures and raw_paths == expected


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--reports-root", type=Path, required=True)
    args.add_argument("--output", type=Path, required=True)
    args.add_argument("--seed", type=int, default=20261113)
    opts = args.parse_args()
    return 0 if build(opts.reports_root.resolve(strict=True), opts.output.absolute(), opts.seed) else 2


if __name__ == "__main__":
    raise SystemExit(main())
