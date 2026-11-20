"""Validate the staged release, frozen offline replay, and token accounting."""

from argparse import ArgumentParser, Namespace
import ast
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from probe_v44 import CAP, PRIVATE_FILES, digest, export, freeze, read, rows

FULL = Path(__file__).resolve().parent.parent / "m2_v61_full"
if FULL.is_dir():
    sys.path.append(str(FULL))
from publish_check import SECRET, grams, public_stage, words

DIRECTORY = "probe_m1m2/m1m2_impl/ledger_judge_v44/"
PRIVATE = "ledger_judge_v44/"
PUBLIC = {DIRECTORY + item for item in ("REPORT.md", "FREEZE.json", "probe_v44.py", "rules_v44.py",
                                         "test_v44.py", "audit_v44.py", "run.sbatch")}
SIGNAL_FIELDS = {"trajectory_id", "stage_id", "C_new", "F_new", "F_corrected", "idle_type",
                 "protected_new_hypothesis", "gen_tokens", "return_tokens", "invalid"}


def key(row):
    return row["trajectory_id"], row["stage_id"]


def decode(blob):
    return list(map(json.loads, blob.decode("utf-8").splitlines()))


def verify_stages(previous, stages, signals, events, sample):
    stage_index = {key(row): row for row in stages}
    signal_index = {key(row): row for row in signals}
    stage_events = {(key(row), row["event"]) for row in events}
    if len(stage_index) != len(stages) or len(stages) != len(signals) or len(stages) != 430:
        raise ValueError("invalid Stage table coverage")
    if list(stage_index) != list(signal_index) or list(stage_index) != list(map(key, previous)):
        raise ValueError("Stage identities or order differ")
    for old, row, signal in zip(previous, stages, signals, strict=True):
        labels = row["labels"]
        if any(row[field] != old[field] for field in
               ("searches", "C_new", "new_docids", "seen_docids", "judge_raw", "outcome")):
            raise ValueError("frozen v4.3 evidence changed")
        if row["ledger_after_v43"] != old["ledger_after"]:
            raise ValueError("frozen v4.3 ledger changed")
        for field in ("invalid", "strict_repeat"):
            if labels.get(field) != old["labels"].get(field):
                raise ValueError("frozen invalid or strict label changed")
        if len(row["items"]) != len(row["searches"]):
            raise ValueError("missing per-search slot")
        original = [item["main_name"] for item in old["items"]] if old["items"] is not None else [None] * len(row["items"])
        if [item["judge_main_name"] for item in row["items"]] != original:
            raise ValueError("frozen Judge extraction changed")
        if labels["protected_new_hypothesis"] and (labels["semantic_repeat"] or labels["stale_return"]):
            raise ValueError("protected Stage received a semantic penalty")
        if labels["semantic_repeat"] and labels["stale_return"]:
            raise ValueError("overlapping semantic labels")
        idle = "strict" if labels.get("strict_repeat") else "semantic" if (
            labels["semantic_repeat"] or labels["stale_return"]) else "none"
        if row["idle_type"] != idle or signal["idle_type"] != idle:
            raise ValueError("idle priority mismatch")
        if signal.keys() != SIGNAL_FIELDS or signal["C_new"] != row["C_new"]:
            raise ValueError("M3 signal schema mismatch")
        for field in ("F_new", "F_corrected"):
            if (type(signal[field]) is not int or signal[field] != int(labels[field])
                    or labels[field] != ((key(row), field) in stage_events)):
                raise ValueError("M3 event or label mismatch")
        for field in ("protected_new_hypothesis", "invalid"):
            if signal[field] is not labels[field]:
                raise ValueError("M3 flag mismatch")
        if any(type(signal[cost]) is not int or signal[cost] < 0 for cost in ("gen_tokens", "return_tokens")):
            raise ValueError("invalid M3 token count")
    for event in events:
        if not event["var"] or event["key"][0] != event["var"]:
            raise ValueError("event without concrete var")
        if not 1 <= event["first_stage"] < event["confirmation_stage"]:
            raise ValueError("candidate event did not recur across Stages")
        sid = event["stage_id"]
        if (event["event"] == "F_new" and sid != event["first_stage"]) or (
                event["event"] == "F_corrected" and sid <= event["confirmation_stage"]):
            raise ValueError("candidate event timing invalid")
        for offset, label in ((-1, "before"), (0, "current"), (1, "after")):
            adjacent = stage_index.get((event["trajectory_id"], sid + offset), {})
            if event["search_window"][label] != adjacent.get("searches", []):
                raise ValueError("unbound event search window")
    seen = set()
    for entry in sample:
        row = stage_index[key(entry)]
        index = entry["query_index"] - 1
        if index < 0 or entry != {**{f: row[f] for f in ("trajectory_id", "stage_id", "judge_raw")},
                                  "query_index": index + 1, "query": row["searches"][index], **row["items"][index]}:
            raise ValueError("unbound sample search")
        seen.add((*key(entry), index))
    if len(seen) != len(sample) or len(sample) != 70:
        raise ValueError("sample is not 70 distinct search rows")


def private():
    paths = subprocess.check_output(["git", "diff", "--cached", "--name-only", "-z"]).decode().split("\0")
    if set(paths) - {""} != {f"{PRIVATE}{name}.jsonl" for name in PRIVATE_FILES}:
        raise ValueError("unexpected private staged paths")
    files = [subprocess.check_output(["git", "show", f":{PRIVATE}{name}.jsonl"]) for name in PRIVATE_FILES]
    frozen = subprocess.check_output(["git", "show", "HEAD:ledger_judge_v43/stages.jsonl"])
    if any(b"\0" in blob or SECRET.search(blob.decode("utf-8")) for blob in files):
        raise ValueError("private credential scan failed")
    verify_stages(decode(frozen), *(decode(blob) for blob in files))
    print(json.dumps({"frozen_sha256": sha256(frozen).hexdigest(), "credential_matches": 0,
                      "private_sha256": {name: sha256(blob).hexdigest()
                                         for name, blob in zip(PRIVATE_FILES, files, strict=True)}}))


def cost_check(signals, ledger):
    index = {key(row): row for row in signals}
    verified = set()
    for row in rows(ledger):
        location = row["trajectory_id"], row["unit_id"]
        if location not in index:
            continue
        signal = index[location]
        before, after = (row[field]["execution"] for field in ("L_pre", "L_post"))
        if (location in verified or signal["C_new"] != row["C_new"]
                or signal["gen_tokens"] != after["generated_tokens"] - before["generated_tokens"]
                or signal["return_tokens"] != after["return_tokens"] - before["return_tokens"]):
            raise ValueError("signal token counts or credit differ from frozen M2")
        verified.add(location)
    if verified != index.keys():
        raise ValueError("M2 token coverage differs")


def compare(args):
    work = args.out
    before = list(rows(args.v43 / "stages.jsonl"))
    files = {name: work / PRIVATE / f"{name}.jsonl" for name in PRIVATE_FILES}
    stages, signals, events, sample = [list(rows(files[name])) for name in PRIVATE_FILES]
    verify_stages(before, stages, signals, events, sample)
    cost_check(signals, args.fixed / "ledger_states.jsonl")
    calls = read(work / "COUNTS.json")["calls"]
    actual = sum(log.read_text(encoding="utf-8", errors="replace").count("POST /v1/chat/completions")
                 for log in work.glob("server-*.log"))
    if (set(calls) - {"type", "alias"} or actual != sum(calls.values()) or actual > CAP
            or len(list((work / "requests").rglob("*.json"))) != actual):
        raise ValueError("Judge call receipts disagree")
    with TemporaryDirectory(prefix="release-replay-", dir=work) as folder:
        replica = Path(folder)
        (replica / "requests").symlink_to(work / "requests", target_is_directory=True)
        export(Namespace(**{**vars(args), "out": replica, "preflight": False, "replay": True, "url": None}))
        compare_paths = [f"{PRIVATE}{name}.jsonl" for name in PRIVATE_FILES] + [
            "COUNTS.json", "new_aliases.jsonl", "REPORT.md", "FREEZE.json"]
        if any(digest(replica / path) != digest(work / path) for path in compare_paths):
            raise ValueError("offline replay differs from frozen outputs")

    manifest = read(args.manifest)
    audit_freeze = freeze(args.country_catalog)
    if manifest.keys() != PUBLIC or json.loads(manifest[DIRECTORY + "FREEZE.json"]["text"]) != audit_freeze:
        raise ValueError("public release paths or freeze metadata mismatch")
    if manifest[DIRECTORY + "REPORT.md"]["text"] != (work / "REPORT.md").read_text(encoding="utf-8"):
        raise ValueError("staged public report differs from replay")
    public, literals = set(), set()
    for path, rec in manifest.items():
        body = rec["text"]
        sha = sha256(body.encode()).hexdigest()
        code_hash = audit_freeze["code_sha256"].get(Path(path).name)
        if sha != rec["sha256"] or (code_hash and sha != code_hash) or SECRET.search(body):
            raise ValueError("public scan or frozen source fingerprint mismatch")
        public.update(grams(body))
        if path.endswith(".py"):
            literals.update(tuple(words(node.value)) for node in ast.walk(ast.parse(body))
                            if isinstance(node, ast.Constant) and isinstance(node.value, str))

    def check(text):
        tokens = tuple(words(text))
        if public.intersection(grams(text)) or (len(tokens) >= 3 and tokens in literals):
            raise ValueError("protected text matches staged public release")

    plan = read(args.previous / "plan.json")
    selected = {row["trajectory_id"] for row in before}
    if set(plan) != selected:
        raise ValueError("frozen plan scope differs")
    for track in plan.values():
        payload = track["payload"]
        check(payload["question"])
        for entity in payload["entities"]:
            check(entity["name"])
            check(entity["role"])
        for frame in payload["stages"]:
            check(frame["thought_tail"])
            for query in frame["searches"]:
                check(query)
    for row in rows(args.root / "supplement-m1-192125/stages.jsonl"):
        if row["trajectory_id"] in selected:
            for event in row["tool_events"]:
                check(event["return_text"])
    if any(SECRET.search(path.read_text(encoding="utf-8")) for path in files.values()):
        raise ValueError("private credential scan failed")
    print(json.dumps({"audit": "PASS", "judge_calls": actual, "m2_stages": len(signals),
                      "manifest_sha256": digest(args.manifest), "frozen_sha256": digest(args.v43 / "stages.jsonl"),
                      "private_sha256": {name: digest(path) for name, path in files.items()}}))


def main():
    parser = ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("private")
    sub.add_parser("public").add_argument("manifest", type=Path)
    verify = sub.add_parser("compare")
    verify.add_argument("manifest", type=Path)
    for field in ("root", "fixed", "prep", "previous", "v42", "v43", "country_catalog", "out"):
        verify.add_argument("--" + field.replace("_", "-"), required=True, type=Path)
    argv = sys.argv[1:]
    if argv and argv[0] not in {"private", "public", "compare", "-h", "--help"}:
        argv.insert(0, "compare")
    args = parser.parse_args(argv)
    if args.mode == "public":
        public_stage(args.manifest, allowed=PUBLIC)
    elif args.mode == "private":
        private()
    else:
        compare(args)


if __name__ == "__main__":
    main()
