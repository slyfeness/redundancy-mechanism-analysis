"""Reconstruct every prefix from saved receipts and scan both commit payloads."""

from argparse import ArgumentParser
import ast
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from runner import EXPECTED, LIMIT, intake, report
from prepare_full import read
from publish_check import SECRET, grams, public_stage, words
from state import Ledger, parse

DIR = "probe_m1m2/m1m2_impl/ledger_judge_v2/"
PUBLIC = {DIR + leaf for leaf in ("REPORT.md", "runner.py", "state.py", "test_state.py", "run.sbatch", "audit.py")}
LABEL_FIELDS = {"invalid", "strict_repeat", "semantic_repeat", "wrong_candidate", "F_new", "F_corrected", "resolved"}
PRIVATE = {"stages.jsonl": {"trajectory_id", "stage_id", "ledger", "ledger_tokens", "omitted_gap_entries", "searches",
                            "judge_raw", "judge_validated", "labels", "C_new", "outcome"},
           "ledger_final.jsonl": {"trajectory_id", "ledger", "ledger_tokens", "omitted_gap_entries", "outcome"}}


def jsonl(blob):
    return [json.loads(line) for line in blob.splitlines()]


def private():
    listing = subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"]).decode()
    if set(listing.split("\0")) - {""} != {"ledger_judge_v2/" + leaf for leaf in PRIVATE}:
        raise ValueError("unexpected private staged paths")
    manifest = {}
    for leaf, fields in PRIVATE.items():
        raw = subprocess.check_output(["git", "show", f":ledger_judge_v2/{leaf}"])
        if SECRET.search(raw.decode("utf-8")) or b"\0" in raw:
            raise ValueError("private credential scan failed")
        rows = jsonl(raw)
        if len(rows) != (430 if leaf == "stages.jsonl" else 40) or any(r.keys() != fields for r in rows):
            raise ValueError("private inventorial mismatch")
        for row in rows:
            if not 0 <= row["ledger_tokens"] <= 400:
                raise ValueError("private ledger over cap")
            if leaf == "stages.jsonl":
                tags = row["labels"]
                assert tags.keys() == ({"invalid"} if tags["invalid"] else LABEL_FIELDS)
        manifest[leaf] = sha256(raw).hexdigest()
    print(json.dumps({"private_sha256": manifest, "credential_matches": 0}))


def replay(work, selection, tokenizer):
    raw = {}
    for leaf in PRIVATE:
        raw[leaf] = (work / "ledger_judge_v2" / leaf).read_bytes()
    stage_rows, final_rows = (jsonl(raw[leaf]) for leaf in PRIVATE)
    entries = {(row["trajectory_id"], row["stage_id"]): row for row in stage_rows}
    finals = {row["trajectory_id"]: row for row in final_rows}
    assert len(entries) == len(stage_rows) == EXPECTED and set(finals) == set(selection)
    calls, before, after, skips = 0, 0, 0, 0
    payloads = set()
    for tid, source in selection.items():
        track = source["track"]
        payload = track["payload"]
        state = Ledger(payload["entities"], source["aliases"])
        proved = {}
        for frame in payload["stages"]:
            sid = frame["stage_id"]
            expected, size, visible = state.render(source["claims"], proved, sid - 1, tokenizer)
            sent = {"question": payload["question"], "entities": payload["entities"], "ledger": expected,
                    "thought_tail": frame["thought_tail"], "searches": frame["searches"]}
            sealed = sha256(json.dumps(sent, ensure_ascii=False).encode()).hexdigest()
            row = entries[tid, sid]
            assert (row["ledger"], row["ledger_tokens"], row["searches"], row["outcome"], row["omitted_gap_entries"]) == (
                expected, size, frame["searches"], track["outcome"], len(state.gaps) - len(visible))
            attempts = row["judge_raw"]
            assert len(attempts) in (1, 2)
            results = []
            for i, exported in enumerate(attempts, 1):
                identity = work / "requests" / str(sid) / tid / f"{i}.json"
                payloads.add(identity)
                receipt = read(identity)
                assert sealed == receipt["payload_sha256"]
                assert exported == {"output": receipt["raw_output"], "error": receipt["error"],
                                    "revision": receipt.get("revision", "original")}
                results.append(parse(receipt["parsed"], set(state.entities), visible,
                                     [sent["thought_tail"], *sent["searches"]], expected,
                                     searching=bool(sent["searches"])))
            output = results[-1]
            before += results[0] is None
            after += output is None
            skips += len(results) == 1 and output is None
            calls += len(results)
            assert len(results) == 1 or results[0] is None
            assert row["judge_validated"] == output
            assert row["labels"] == state.apply(sid, sent["searches"], output)
            assert row["C_new"] == track["metrics"][str(sid)]["C_new"]
            assert not set(row["C_new"]) & proved.keys()
            proved.update({k: sid for k in row["C_new"]})
        ledger, size, visible = state.render(source["claims"], proved, len(payload["stages"]), tokenizer)
        assert finals[tid] == {"trajectory_id": tid, "ledger": ledger, "ledger_tokens": size,
                              "omitted_gap_entries": len(state.gaps) - len(visible), "outcome": track["outcome"]}
    assert set((work / "requests").rglob("*.json")) == payloads and EXPECTED <= calls <= LIMIT
    checks = work / "release_check"
    checks.mkdir(mode=0o700, exist_ok=True)
    report(checks, stage_rows, final_rows, before, after, skips, calls - EXPECTED, sum(
        bool(variants) for row in selection.values() for variants in row["aliases"].values()))
    assert read(checks / "SUMMARY.json") == read(work / "SUMMARY.json")
    assert (checks / "REPORT.md").read_bytes() == (work / "REPORT.md").read_bytes()
    return {leaf: sha256(data).hexdigest() for leaf, data in raw.items()}, calls


def compare(args):
    from transformers import AutoTokenizer

    selection = intake(args)
    tok = AutoTokenizer.from_pretrained(args.model, local_files_only=True, model_max_length=131072)
    hashes, calls = replay(args.work, selection, tok)
    arrived = sum(log.read_text(encoding="utf-8", errors="replace").count("POST /v1/chat/completions")
                  for log in args.work.glob("server-*.log"))
    assert arrived == calls <= LIMIT
    recovery = args.work / "transport_recovery.json"
    if recovery.exists():
        receipt = read(recovery)
        assert len(list((args.work / "transport_abort" / "requests").rglob("*.json"))) == receipt["archived_unsent"]
    paths = read(args.manifest)
    assert paths.keys() == PUBLIC
    protected = set()
    for item in selection.values():
        payload = item["track"]["payload"]
        protected.add(payload["question"])
        protected.update(e[k] for e in payload["entities"] for k in ("name", "role"))
        protected.update(c["claim"] for c in item["claims"])
        for frame in payload["stages"]:
            protected.add(frame["thought_tail"])
            protected.update(frame["searches"])
    public_grams, literals = set(), set()
    for path, row in paths.items():
        text = row["text"]
        if row["sha256"] != sha256(text.encode()).hexdigest() or SECRET.search(text):
            raise ValueError("unexpected staged content")
        public_grams.update(grams(text))
        if path.endswith(".py"):
            literals.update(tuple(words(node.value)) for node in ast.walk(ast.parse(text))
                            if isinstance(node, ast.Constant) and isinstance(node.value, str))
    for value in protected:
        if public_grams.intersection(grams(value)) or (len(words(value)) >= 3 and tuple(words(value)) in literals):
            raise ValueError("protected task text matched staged content")
    report_text = paths[DIR + "REPORT.md"]["text"]
    assert report_text == (args.work / "REPORT.md").read_text(encoding="utf-8")
    assert len(report_text.splitlines()) <= 20
    print(json.dumps({"audit": "PASS", "calls": calls, "manifest_sha256": sha256(args.manifest.read_bytes()).hexdigest(),
                      "private_sha256": hashes, "report_lines": len(report_text.splitlines())}))


def main():
    parser = ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("private")
    sub.add_parser("public").add_argument("manifest", type=Path)
    check = sub.add_parser("compare")
    for field in ("manifest", "work", "previous", "fixed", "prep", "model"):
        check.add_argument(field, type=Path)
    args = parser.parse_args()
    if args.mode == "private":
        private()
    elif args.mode == "public":
        public_stage(args.manifest, allowed=PUBLIC)
    else:
        compare(args)


if __name__ == "__main__":
    main()
