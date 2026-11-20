"""Reconstruct the causal input and scan exact staged publication payloads."""

from argparse import ArgumentParser
import ast
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from probe_v3 import EXPECTED, LABELS, LIMIT, summarize, verify_scope
from prepare_full import read
from publish_check import SECRET, grams, public_stage, words
from state_v3 import StageLedger, extract

DIRECTORY = "probe_m1m2/m1m2_impl/ledger_judge_v3/"
PUBLIC = {DIRECTORY + leaf for leaf in ("REPORT.md", "probe_v3.py", "state_v3.py", "test_state.py", "run.sbatch", "audit.py")}
PRIVATE = {"stages.jsonl": {"trajectory_id", "stage_id", "ledger", "ledger_tokens", "omitted_gap_entries", "searches",
                            "judge_raw", "judge_validated", "discarded_mentions", "labels", "C_new", "outcome"},
           "events.jsonl": {"trajectory_id", "event", "stage_id", "id", "role", "candidate", "stance", "resolves",
                            "search_window"}}


def jsonl(data):
    return [json.loads(line) for line in data.splitlines()]


def scan_private():
    names = subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"]).decode().split("\0")
    assert set(names) - {""} == {"ledger_judge_v3/" + name for name in PRIVATE}
    verified = {}
    for filename, keys in PRIVATE.items():
        raw = subprocess.check_output(["git", "show", f":ledger_judge_v3/{filename}"])
        if b"\0" in raw or SECRET.search(raw.decode()):
            raise ValueError("private credential scan failed")
        rows = jsonl(raw)
        assert all(row.keys() == keys for row in rows)
        if filename == "stages.jsonl":
            assert len(rows) == EXPECTED and len({(row["trajectory_id"], row["stage_id"]) for row in rows}) == EXPECTED
            assert all(0 <= row["ledger_tokens"] <= 400 and row["labels"].keys() ==
                       ({"invalid"} if row["labels"]["invalid"] else {"invalid", *LABELS}) for row in rows)
        verified[filename] = sha256(raw).hexdigest()
    print(json.dumps({"private_sha256": verified, "credential_matches": 0}))


def replay(work, selection, tok):
    output = work / "ledger_judge_v3"
    raw = {name: (output / name).read_bytes() for name in PRIVATE}
    entries = jsonl(raw["stages.jsonl"])
    events = jsonl(raw["events.jsonl"])
    expected_rows = {(row["trajectory_id"], row["stage_id"]): row for row in entries}
    assert len(expected_rows) == len(entries) == EXPECTED
    paths, all_events = set(), []
    before, after, calls = 0, 0, 0
    for tid, item in selection.items():
        track = item["track"]
        task = track["payload"]
        state = StageLedger(task["entities"], item["aliases"])
        conditions = {f"c{idx}" for idx in range(1, len(item["claims"]) + 1)}
        roles, proved = set(state.entities), {}
        for sid, frame in enumerate(task["stages"], 1):
            assert sid == frame["stage_id"]
            observed = {item["claims"][int(c["id"][1:]) - 1]["id"]: c["stage_id"] for c in frame["pre"]["conditions"]}
            assert proved == observed
            ledger, count, visible = state.render(item["claims"], proved, sid - 1, tok)
            payload = {"question": task["question"], "entities": task["entities"], "ledger": ledger,
                       "thought_tail": frame["thought_tail"], "searches": frame["searches"]}
            expected = expected_rows[tid, sid]
            assert (ledger, count, len(state.gaps)-len(visible), frame["searches"], track["outcome"]) == (
                expected["ledger"], expected["ledger_tokens"], expected["omitted_gap_entries"],
                expected["searches"], expected["outcome"])
            digest = sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()
            attempts = expected["judge_raw"]
            assert len(attempts) in (1, 2)
            drops, results = [], []
            for number, raw_result in enumerate(attempts, 1):
                path = work / "requests" / str(sid) / tid / f"{number}.json"
                paths.add(path)
                receipt = read(path)
                assert receipt["payload_sha256"] == digest and raw_result == {
                    "raw": receipt["raw"], "error": receipt["error"]}
                valid, discarded = extract(receipt["parsed"], roles, conditions,
                                           [payload["thought_tail"], *payload["searches"]], ledger)
                results.append(valid)
                drops.extend({"attempt": number, **row} for row in discarded)
            assert len(results) == 1 or results[0] is None
            assert results[-1] == expected["judge_validated"] and drops == expected["discarded_mentions"]
            before += results[0] is None
            after += results[-1] is None
            calls += len(results)
            tags, found = state.apply(sid, frame["searches"], results[-1])
            assert tags == expected["labels"]
            c_new = track["metrics"][str(sid)]["C_new"]
            assert c_new == expected["C_new"] and not set(c_new) & proved.keys()
            proved.update({cid: sid for cid in c_new})
            for event in found:
                frames = task["stages"]
                window = {key: frames[idx]["searches"] if 0 <= idx < len(frames) else []
                          for key, idx in (("before", sid-2), ("current", sid-1), ("after", sid))}
                all_events.append({"trajectory_id": tid, **event, "search_window": window})
    event_key = lambda row: (row["trajectory_id"], row["stage_id"], row["id"])
    assert sorted(all_events, key=event_key) == sorted(events, key=event_key)
    assert len({event_key(row) for row in events}) == len(events)
    assert set((work/"requests").rglob("*.json")) == paths
    assert EXPECTED <= calls <= min(LIMIT, 2*EXPECTED)
    served = sum(log.read_text(encoding="utf-8", errors="replace").count("POST /v1/chat/completions")
                 for log in work.glob("server-*.log"))
    assert served == calls
    check = work/"release_check"
    check.mkdir(mode=0o700, exist_ok=True)
    summarize(check, entries, events, before, after, calls-EXPECTED)
    assert read(check/"SUMMARY.json") == read(work/"SUMMARY.json")
    assert (check/"REPORT.md").read_bytes() == (work/"REPORT.md").read_bytes()
    return calls, {name: sha256(data).hexdigest() for name, data in raw.items()}


def compare(args):
    from transformers import AutoTokenizer

    selection = verify_scope(args)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, model_max_length=131072)
    calls, hashes = replay(args.work, selection, tokenizer)
    sources, literals, overlap = set(), set(), set()
    for row in selection.values():
        payload = row["track"]["payload"]
        sources.add(payload["question"])
        sources.update(e[k] for e in payload["entities"] for k in ("name", "role"))
        sources.update(claim["claim"] for claim in row["claims"])
        for frame in payload["stages"]:
            sources.add(frame["thought_tail"])
            sources.update(frame["searches"])
    manifest = read(args.manifest)
    assert manifest.keys() == PUBLIC
    for path, item in manifest.items():
        text = item["text"]
        if SECRET.search(text) or sha256(text.encode()).hexdigest() != item["sha256"]:
            raise ValueError("unexpected public content")
        overlap.update(grams(text))
        if path.endswith(".py"):
            literals.update(tuple(words(node.value)) for node in ast.walk(ast.parse(text))
                            if isinstance(node, ast.Constant) and isinstance(node.value, str))
    if any(overlap.intersection(grams(value)) or (len(words(value)) >= 3 and tuple(words(value)) in literals)
           for value in sources):
        raise ValueError("protected task data matched staged publication")
    assert manifest[DIRECTORY+"REPORT.md"]["text"] == (args.work/"REPORT.md").read_text(encoding="utf-8")
    print(json.dumps({"audit": "PASS", "calls": calls, "manifest_sha256": sha256(args.manifest.read_bytes()).hexdigest(),
                      "private_sha256": hashes}))


def main():
    parser = ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("private")
    sub.add_parser("public").add_argument("manifest", type=Path)
    audit = sub.add_parser("compare")
    for name in ("manifest", "work", "previous", "fixed", "prep", "model"):
        audit.add_argument(name, type=Path)
    args = parser.parse_args()
    if args.mode == "private":
        scan_private()
    elif args.mode == "public":
        public_stage(args.manifest, allowed=PUBLIC)
    else:
        compare(args)


if __name__ == "__main__":
    main()
